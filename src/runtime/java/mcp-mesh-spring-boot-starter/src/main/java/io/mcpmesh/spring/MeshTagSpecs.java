package io.mcpmesh.spring;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Wire form of a consumer-side dependency tag list (issue #1572).
 *
 * <p>Java annotations can only carry {@code String[]}, so a tag-level OR group
 * is written inline: {@code "python|typescript"} means python OR typescript.
 * The registry contract — what Python and TypeScript send — is a nested array,
 * {@code ["addition", ["python", "typescript"]]}, so the SDK expands every
 * {@code a|b} entry into an inner array before the tags leave the process.
 *
 * <p>Each alternative keeps its own operator. A {@code +} alternative matches
 * like a plain one but scores higher ({@code "+python|typescript"} prefers
 * python). A {@code -} alternative never counts as a match; it only rejects
 * providers carrying that tag — so {@code "python|-legacy"} means python
 * required and legacy forbidden, and an all-{@code -} group can never match
 * (logged as a WARN). The order of the alternatives carries no meaning: the
 * registry accepts a provider matching any of them and ranks candidates by
 * score.
 *
 * <p>One pair of surrounding parentheses ({@code "(python|typescript)"}) and
 * whitespace around each alternative are tolerated; empty alternatives are
 * dropped. A group left with one alternative degrades to that plain tag, and a
 * group left with none is dropped with a WARN.
 */
public final class MeshTagSpecs {

    private static final Logger log = LoggerFactory.getLogger(MeshTagSpecs.class);

    // Tag specs are re-serialized on every spec build; warn once per tag.
    private static final Set<String> WARNED = ConcurrentHashMap.newKeySet();

    private MeshTagSpecs() {}

    /**
     * Expand a tag list into its wire form: plain tags stay strings, each
     * {@code a|b} entry becomes a {@code List<String>} OR group.
     *
     * @param tags the declared tags (may be {@code null})
     * @return the wire-form list; never {@code null}
     */
    public static List<Object> toWire(Collection<String> tags) {
        List<Object> wire = new ArrayList<>();
        if (tags == null) {
            return wire;
        }
        for (String tag : tags) {
            if (tag == null || tag.indexOf('|') < 0) {
                wire.add(tag);
                continue;
            }
            String body = tag.trim();
            if (body.length() >= 2 && body.charAt(0) == '(' && body.charAt(body.length() - 1) == ')') {
                body = body.substring(1, body.length() - 1);
            }
            List<String> group = new ArrayList<>();
            for (String alternative : body.split("\\|")) {
                String trimmed = alternative.trim();
                if (!trimmed.isEmpty()) {
                    group.add(trimmed);
                }
            }
            if (group.isEmpty()) {
                warnOnce(tag, "Tag '{}' is an OR group with no alternatives — ignoring it.");
            } else if (group.size() == 1) {
                String only = group.get(0);
                if (only.startsWith("+") || only.startsWith("-")) {
                    // As a one-element group "+a" would be required and "-a"
                    // could never match; as a plain tag they are preferred /
                    // excluded. The plain reading is the likely intent.
                    warnOnce(tag, "Tag '{}' has a single alternative — the '|' is ignored and it is "
                        + "sent as the plain tag '" + only + "'.");
                }
                wire.add(only);
            } else {
                if (group.stream().allMatch(t -> t.startsWith("-"))) {
                    warnOnce(tag, "Tag '{}' is an OR group of only '-' exclusions, which can never "
                        + "match: a '-' alternative rejects providers carrying the tag but never "
                        + "counts as a match. Write the exclusions as separate tags instead.");
                }
                wire.add(group);
            }
        }
        return wire;
    }

    private static void warnOnce(String tag, String message) {
        if (WARNED.add(tag)) {
            log.warn(message, tag);
        }
    }

    /** Array overload of {@link #toWire(Collection)}. */
    public static List<Object> toWire(String[] tags) {
        return tags == null ? new ArrayList<>() : toWire(Arrays.asList(tags));
    }

    /** Whether any tag is written as an {@code a|b} OR group. */
    public static boolean hasAlternatives(String[] tags) {
        if (tags == null) {
            return false;
        }
        for (String tag : tags) {
            if (tag != null && tag.indexOf('|') >= 0) {
                return true;
            }
        }
        return false;
    }
}
