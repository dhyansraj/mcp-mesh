package tracing

import (
	"math"
	"math/rand"
	"sort"
	"testing"
	"unsafe"
)

// TestHistogramBucketCountCoversRange pins the constant that the whole layout
// depends on. histBucketCount is derived by hand from the index formula, so it
// is the one number here nothing else would catch: too small and Record writes
// out of range (a panic, on the hottest path in the accumulator); too large and
// every key silently pays for buckets no value can reach.
func TestHistogramBucketCountCoversRange(t *testing.T) {
	if got := histIndex(histMaxValueMs); got != histBucketCount-1 {
		t.Fatalf("histIndex(max) = %d, want %d — histBucketCount is wrong", got, histBucketCount-1)
	}
	// Anything beyond the addressable range clamps into that same last bucket
	// rather than escaping the array.
	if got := histIndex(math.MaxInt64); got != histBucketCount-1 {
		t.Fatalf("histIndex(MaxInt64) = %d, want %d", got, histBucketCount-1)
	}
	if got := histIndex(-5); got != 0 {
		t.Fatalf("histIndex(-5) = %d, want 0", got)
	}
}

// TestHistogramIndexIsMonotonicAndContiguous walks the whole addressable range
// and holds the two properties the bucket search relies on: indices never go
// backwards as the value grows, and every value lands at or below its bucket's
// stated upper bound (so Quantile's answer is never an understatement).
func TestHistogramIndexIsMonotonicAndContiguous(t *testing.T) {
	prev := -1
	check := func(v int64) {
		i := histIndex(v)
		if i < prev {
			t.Fatalf("histIndex(%d) = %d went backwards from %d", v, i, prev)
		}
		if i < 0 || i >= histBucketCount {
			t.Fatalf("histIndex(%d) = %d out of range", v, i)
		}
		if ub := histUpperBound(i); v > ub {
			t.Fatalf("histIndex(%d) = %d whose upper bound %d is BELOW the value", v, i, ub)
		}
		prev = i
	}

	// Exhaustive across the exact region and the first few octaves, then every
	// octave boundary and its neighbours the rest of the way up.
	for v := int64(0); v < 4096; v++ {
		check(v)
	}
	for shift := uint(12); shift < 32; shift++ {
		base := int64(1) << shift
		for _, v := range []int64{base - 1, base, base + 1, base + base/2, 2*base - 1} {
			if v <= histMaxValueMs {
				check(v)
			}
		}
	}
}

// TestHistogramExactBelowLinearLimit: under 16 ms every bucket holds exactly one
// integer, so there is no estimate at all down there — the region most edges in
// a healthy mesh live in.
func TestHistogramExactBelowLinearLimit(t *testing.T) {
	for v := int64(0); v < histLinearLimit; v++ {
		var h latencyHistogram
		h.Record(v)
		if got := h.Quantile(0.99); got != v {
			t.Fatalf("single sample %d ms: P99 = %d, want it exact", v, got)
		}
	}
}

// TestHistogramWorstCaseRelativeError is the accuracy bound the design claims:
// the reported value never understates, and overstates by at most 12.5%.
func TestHistogramWorstCaseRelativeError(t *testing.T) {
	var worst float64
	for i := 0; i < histBucketCount; i++ {
		ub := histUpperBound(i)
		if ub > histMaxValueMs {
			t.Fatalf("bucket %d upper bound %d exceeds the addressable max", i, ub)
		}
		// The smallest value in this bucket is one past the previous bucket's
		// top, and it is the value the upper bound overstates the most.
		var lo int64
		if i == 0 {
			lo = 0
		} else {
			lo = histUpperBound(i-1) + 1
		}
		if lo == 0 {
			continue
		}
		if histIndex(lo) != i {
			t.Fatalf("bucket %d: lowest value %d indexes to %d instead", i, lo, histIndex(lo))
		}
		if rel := float64(ub-lo) / float64(lo); rel > worst {
			worst = rel
		}
	}
	const bound = 1.0 / float64(histSubBucketCount) // 12.5%
	if worst > bound+1e-12 {
		t.Fatalf("worst-case relative error %.4f exceeds the stated bound %.4f", worst, bound)
	}
	if worst < bound/2 {
		t.Fatalf("worst-case error %.4f is far below the stated %.4f — the doc comment "+
			"is claiming a looser bound than the layout delivers, which is its own bug", worst, bound)
	}
}

// TestHistogramQuantileTracksExactP99 compares the estimate against the sorted
// exact answer the reservoir used to compute, over distributions shaped like
// real traffic: a fast body with a slow tail. The estimate must bracket the
// truth from above, within the bound.
func TestHistogramQuantileTracksExactP99(t *testing.T) {
	cases := []struct {
		name string
		gen  func(i int) int64
		n    int
	}{
		{"sub-millisecond body, all zero", func(int) int64 { return 0 }, 1000},
		{"tight around 3ms", func(i int) int64 { return int64(2 + i%3) }, 1000},
		{"fast body with a 2s tail", func(i int) int64 {
			if i%100 == 0 {
				return 2000 + int64(i%37)
			}
			return int64(1 + i%9)
		}, 5000},
		{"multi-second spread", func(i int) int64 { return int64(500 + i*7) }, 3000},
		{"single sample", func(int) int64 { return 12345 }, 1},
		{"two samples", func(i int) int64 { return int64(1 + i*4000) }, 2},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var h latencyHistogram
			exact := make([]int64, 0, tc.n)
			for i := 0; i < tc.n; i++ {
				v := tc.gen(i)
				h.Record(v)
				exact = append(exact, v)
			}
			sort.Slice(exact, func(a, b int) bool { return exact[a] < exact[b] })
			idx := int(math.Ceil(float64(len(exact))*0.99)) - 1
			if idx < 0 {
				idx = 0
			}
			want := exact[idx]

			got := h.Quantile(0.99)
			if got < want {
				t.Fatalf("P99 estimate %d UNDERSTATES the true %d", got, want)
			}
			if want > 0 {
				rel := float64(got-want) / float64(want)
				if rel > 1.0/float64(histSubBucketCount)+1e-12 {
					t.Fatalf("P99 estimate %d overstates the true %d by %.3f%%", got, want, rel*100)
				}
			} else if got != 0 {
				t.Fatalf("P99 estimate %d for an all-zero sample, want 0", got)
			}
		})
	}
}

// TestHistogramQuantileRandomised is the same contract under randomised input,
// so the accuracy claim does not rest on hand-picked shapes.
func TestHistogramQuantileRandomised(t *testing.T) {
	rng := rand.New(rand.NewSource(1531))
	for round := 0; round < 200; round++ {
		var h latencyHistogram
		n := 1 + rng.Intn(400)
		exact := make([]int64, 0, n)
		for i := 0; i < n; i++ {
			// Log-uniform over 0..~1 hour, which is the shape the layout is for.
			v := int64(math.Pow(2, rng.Float64()*22))
			h.Record(v)
			exact = append(exact, v)
		}
		sort.Slice(exact, func(a, b int) bool { return exact[a] < exact[b] })
		idx := int(math.Ceil(float64(n)*0.99)) - 1
		if idx < 0 {
			idx = 0
		}
		want := exact[idx]
		got := h.Quantile(0.99)
		if got < want {
			t.Fatalf("round %d: P99 estimate %d understates the true %d", round, got, want)
		}
		if want > 0 {
			if rel := float64(got-want) / float64(want); rel > 1.0/float64(histSubBucketCount)+1e-12 {
				t.Fatalf("round %d: P99 estimate %d overstates the true %d by %.3f%%", round, got, want, rel*100)
			}
		}
	}
}

// TestHistogramMemoryIsIndependentOfTraffic is half the point of the change: the
// reservoir it replaced grew to 10,000 int64 per key. Nothing here grows, and
// the rolling window does not grow it either — two fixed generations, whatever
// the traffic.
func TestHistogramMemoryIsIndependentOfTraffic(t *testing.T) {
	var quiet, busy latencyHistogram
	quiet.Record(5)
	for i := 0; i < 200000; i++ {
		busy.Record(int64(i % 5000))
	}
	if unsafe.Sizeof(quiet) != unsafe.Sizeof(busy) {
		t.Fatalf("histogram grew with traffic: %d vs %d bytes",
			unsafe.Sizeof(quiet), unsafe.Sizeof(busy))
	}
	// The window is bounded by two generations, so the sample population a
	// quantile is computed over never exceeds twice the rotation size no matter
	// how many calls the edge saw.
	if got := busy.Count(); got > 2*histRotateSamples {
		t.Fatalf("window holds %d samples, want at most %d", got, 2*histRotateSamples)
	}
	if got := busy.Count(); got < histRotateSamples {
		t.Fatalf("window holds %d samples, want at least %d", got, histRotateSamples)
	}
}

// TestHistogramCountersCannotOverflow: the generation counters are uint32, which
// is only safe because Record rotates AT histRotateSamples. Pinned so that
// raising that constant past 2^32 without widening the counters fails here
// rather than silently wrapping a bucket in production.
func TestHistogramCountersCannotOverflow(t *testing.T) {
	if histRotateSamples > math.MaxUint32 {
		t.Fatalf("histRotateSamples %d exceeds the uint32 generation counters", histRotateSamples)
	}
	var h latencyHistogram
	// Every sample into one bucket is the worst case for a bucket counter.
	for i := 0; i < histRotateSamples*3; i++ {
		h.Record(7)
	}
	if h.current.count > histRotateSamples || h.previous.count > histRotateSamples {
		t.Fatalf("generation counts %d/%d exceed the rotation size %d",
			h.current.count, h.previous.count, histRotateSamples)
	}
	if h.current.buckets[7] > histRotateSamples || h.previous.buckets[7] > histRotateSamples {
		t.Fatalf("bucket counts %d/%d exceed the rotation size %d",
			h.current.buckets[7], h.previous.buckets[7], histRotateSamples)
	}
}

// TestHistogramSpikeAgesOutOfTheWindow is the behaviour the window exists for,
// and the one a single accumulating histogram would have lost: after an incident
// and enough subsequent healthy traffic, the P99 comes back down.
//
// The old reservoir did this because it held the last 10,000 samples. An edge
// stat key is refreshed on every call, so a busy edge's key never ages out and
// nothing else would ever clear it.
func TestHistogramSpikeAgesOutOfTheWindow(t *testing.T) {
	var h latencyHistogram

	// The incident: a full generation of 5-second calls.
	for i := 0; i < histRotateSamples; i++ {
		h.Record(5000)
	}
	if got := h.Quantile(0.99); got < 5000 {
		t.Fatalf("during the incident P99 = %d, want >= 5000", got)
	}

	// Recovery, still inside the two-generation window: the spike is in the
	// PREVIOUS generation and must still count. This is the half that says the
	// window is a window and not a reset.
	for i := 0; i < histRotateSamples/2; i++ {
		h.Record(3)
	}
	if got := h.Quantile(0.99); got < 5000 {
		t.Fatalf("one generation after the incident P99 = %d, want the spike still "+
			"inside the window (>= 5000)", got)
	}

	// Two full generations of healthy traffic later, the incident has left the
	// window entirely.
	for i := 0; i < 2*histRotateSamples; i++ {
		h.Record(3)
	}
	if got := h.Quantile(0.99); got != 3 {
		t.Fatalf("after the spike aged out P99 = %d, want 3 — a P99 that never "+
			"recovers is the regression this window prevents", got)
	}
}

// TestHistogramWindowIsAtLeastTheOldReservoir: the rotation size is what makes
// the window comparable to the reservoir it replaced, so a quantile is never
// computed over a SMALLER recent population than the old code used.
func TestHistogramWindowIsAtLeastTheOldReservoir(t *testing.T) {
	var h latencyHistogram
	for i := 1; i <= 4*histRotateSamples; i++ {
		h.Record(int64(i % 11))
		if got := h.Count(); got < uint64(min(i, histRotateSamples)) {
			t.Fatalf("after %d samples the window holds only %d", i, got)
		}
	}
}

// TestHistogramEmptyIsZero: a histogram nobody wrote to reports 0 rather than
// reaching into an empty slice, which is what the sorted-reservoir version had
// to guard against with index clamping.
func TestHistogramEmptyIsZero(t *testing.T) {
	var h latencyHistogram
	if got := h.Quantile(0.99); got != 0 {
		t.Fatalf("empty histogram P99 = %d, want 0", got)
	}
	if h.Count() != 0 {
		t.Fatalf("empty histogram count = %d, want 0", h.Count())
	}
}
