package tracing

import (
	"math"
	"math/bits"
)

// latencyHistogram is a fixed-size, log-linear histogram over integer
// millisecond latencies, held over a rolling window of recent samples. It
// replaces the per-key reservoir of raw samples that existed only to sort a P99
// at read time (#1531): a reservoir costs memory proportional to TRAFFIC, and
// once edge stats are keyed per provider function there are many more keys to
// pay it on. A histogram costs the same 1,928 bytes whether a key saw one call
// or a billion.
//
// BUCKET LAYOUT — the range that matters here runs from a sub-millisecond
// in-cluster hop to a multi-second LLM turn to a multi-hour MeshJob, five or
// more orders of magnitude. Linear buckets cannot serve both ends: fine enough
// for the fast hop and there are millions of them; coarse enough for the job
// and every fast edge lands in bucket zero. So the layout is log-LINEAR, the
// HdrHistogram shape:
//
//   - [0, 16) ms: one bucket per millisecond. Exact — these values are integers,
//     so the bucket IS the value.
//   - >= 16 ms: each power-of-two octave is cut into 8 equal sub-buckets, so a
//     bucket is 1/8 of its octave wide. Its members are between 1 and 2 octave
//     bases, so a bucket spans between 1/16 and 1/8 of the values it holds.
//
// WORST-CASE ERROR: a bucket at octave o spans 2^(o-3) and its members are at
// least 2^o, so reporting a bucket's UPPER bound overstates a value by at most
// 1/8 = 12.5%, and never understates it. The error is deliberately one-sided —
// a latency dashboard that rounds the wrong way tells you the mesh is faster
// than it is. Below 16 ms the error is exactly zero. GetEdgeStats then clamps
// the estimate to the exactly-tracked MaxMs, so the reported P99 can never
// exceed a latency that was actually observed.
//
// THE WINDOW is the second half of the design and is not a memory measure. The
// reservoir this replaced held the last 10,000 samples, so a latency spike aged
// out of the percentile once 10,000 calls had happened since. A single
// accumulating histogram would NOT: an edge stat key is refreshed on every call,
// so a busy edge's key never ages out and nothing would ever reset it — one bad
// afternoon would sit in that edge's P99 for the life of the process. A P99 that
// cannot recover is a P99 nobody trusts. So the histogram keeps two generations
// and rotates (see histRotateSamples), which restores the old window rather than
// inventing a new one.
//
// min/max/avg stay EXACT and are LIFETIME, as they always were — they are not
// read from here at all, since a running min, max and sum need no samples
// retained. So the P99 alone is both an estimate and windowed, and the pairing
// of a lifetime average with a recent percentile is the same pairing the
// reservoir produced.
//
// Note the accumulator's per-agent and per-model aggregates (the UI's
// MetricsProcessor) do NOT move to this: they hold counters and token sums
// only, never a latency sample, so there is nothing there to bound.
const (
	// histSubBucketBits is log2 of the sub-buckets per octave. 3 => 8
	// sub-buckets => 12.5% worst-case bucket width.
	histSubBucketBits = 3

	// histSubBucketCount is the sub-buckets per octave (8).
	histSubBucketCount = 1 << histSubBucketBits

	// histLinearLimit is the exclusive top of the exact, one-bucket-per-ms
	// region (16). Above it the octave scale takes over, seamlessly: the first
	// octave bucket starts at exactly this value.
	histLinearLimit = histSubBucketCount << 1

	// histMaxValueMs is the largest latency the layout addresses: 2^32-1 ms,
	// just under 50 days. Anything longer is clamped into the final bucket.
	// Nothing is lost by that — MaxMs records the true value exactly.
	histMaxValueMs = int64(1)<<32 - 1

	// histBucketCount is histIndex(histMaxValueMs)+1. Asserted by
	// TestHistogramBucketCountCoversRange rather than left as a claim.
	histBucketCount = 240

	// histRotateSamples is how many observations one generation holds before the
	// histogram rotates. Deliberately the reservoir's old capacity: the window a
	// quantile is computed over is then between histRotateSamples and twice it,
	// which brackets the exactly-10,000 window the reservoir gave. Counted in
	// SAMPLES rather than in wall time for the same reason — a count window is
	// what the old behaviour was, and it needs no clock on the accumulator's
	// hottest path.
	//
	// A quiet edge never rotates and its P99 covers everything it ever saw. That
	// is also unchanged: the old ring buffer never wrapped below 10,000 samples
	// either.
	histRotateSamples = 10000
)

// histGeneration is one window's counters. uint32 is sufficient BY
// CONSTRUCTION, not by estimate: Record rotates the moment count reaches
// histRotateSamples, so no field here can exceed that constant.
type histGeneration struct {
	buckets [histBucketCount]uint32
	count   uint32
}

// latencyHistogram counts observations per bucket over a rolling two-generation
// window. The zero value is ready to use and allocates nothing beyond itself
// (two 960-byte counter arrays plus two counts = 1,928 bytes — byte for byte
// what a single non-windowed uint64-counter version would have cost).
type latencyHistogram struct {
	current  histGeneration
	previous histGeneration
}

// histIndex maps a latency in milliseconds to its bucket.
//
// Values <= 0 (including the sub-millisecond calls that the wire format has
// already truncated to 0 — duration_ms is an integer everywhere upstream) land
// in bucket 0. Values above histMaxValueMs are clamped into the last bucket.
func histIndex(ms int64) int {
	if ms <= 0 {
		return 0
	}
	if ms > histMaxValueMs {
		ms = histMaxValueMs
	}
	if ms < histLinearLimit {
		return int(ms)
	}
	// 2^octave <= ms < 2^(octave+1), so octave >= 4 and shift >= 1.
	octave := bits.Len64(uint64(ms)) - 1
	shift := octave - histSubBucketBits
	sub := int(ms >> shift) // in [8, 16) by construction
	return (shift+1)*histSubBucketCount + (sub - histSubBucketCount)
}

// histUpperBound returns the largest millisecond value that lands in bucket i.
// In the linear region that is the value itself.
func histUpperBound(i int) int64 {
	if i < histLinearLimit {
		return int64(i)
	}
	shift := i/histSubBucketCount - 1
	sub := int64(i%histSubBucketCount + histSubBucketCount)
	return (sub << shift) + (int64(1) << shift) - 1
}

// Record adds one observation, rotating the window first when the current
// generation is full. The rotation is a 964-byte struct copy paid once per
// histRotateSamples observations.
func (h *latencyHistogram) Record(ms int64) {
	if h.current.count >= histRotateSamples {
		h.previous = h.current
		h.current = histGeneration{}
	}
	h.current.buckets[histIndex(ms)]++
	h.current.count++
}

// Count returns the number of observations inside the current window, which is
// not the total ever recorded once the histogram has rotated. The accumulator's
// exact CallCount is the lifetime number.
func (h *latencyHistogram) Count() uint64 {
	return uint64(h.current.count) + uint64(h.previous.count)
}

// Quantile returns the q-th percentile OF THE WINDOW as the UPPER bound of the
// bucket holding it (see the error discussion above), or 0 when nothing has been
// recorded.
//
// The rank is ceil(q*N), 1-based, the same rank formula the sorted-slice
// implementation this replaced used. Over a population that fits entirely in the
// exact sub-16 ms region and has not yet rotated, that makes the answer
// identical to the old one; the estimate and the window are what differ
// elsewhere.
func (h *latencyHistogram) Quantile(q float64) int64 {
	count := h.Count()
	if count == 0 {
		return 0
	}
	rank := uint64(math.Ceil(float64(count) * q))
	if rank < 1 {
		rank = 1
	}
	if rank > count {
		rank = count
	}

	var cumulative uint64
	for i := 0; i < histBucketCount; i++ {
		cumulative += uint64(h.current.buckets[i]) + uint64(h.previous.buckets[i])
		if cumulative >= rank {
			return histUpperBound(i)
		}
	}
	// Unreachable: cumulative reaches count, and rank <= count.
	return histUpperBound(histBucketCount - 1)
}
