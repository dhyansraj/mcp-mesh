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
 * whitespace around each alternative are tolerated. Every {@code |} must
 * separate two non-empty alternatives: {@code "|"}, {@code "a|"},
 * {@code "|a"}, {@code "a||b"}, {@code "()"} and {@code "( | )"} are rejected
 * with an {@link IllegalArgumentException}, because dropping or collapsing
 * the missing alternative would weaken the constraint. The annotation
 * scanners call {@link #validate} so the agent fails at startup, naming the
 * annotated element.
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
     * @throws IllegalArgumentException if an OR group has an empty alternative
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
            List<String> group = alternatives(tag, null);
            if (group.stream().allMatch(t -> t.startsWith("-"))) {
                warnOnce(tag, "Tag '{}' is an OR group of only '-' exclusions, which can never "
                    + "match: a '-' alternative rejects providers carrying the tag but never "
                    + "counts as a match. Write the exclusions as separate tags instead.");
            }
            wire.add(group);
        }
        return wire;
    }

    /**
     * Reject any {@code a|b} tag with an empty alternative. Called by the
     * annotation scanners during context refresh so a malformed selector
     * fails the boot instead of surfacing later in spec building.
     *
     * @param tags  the declared tags (may be {@code null})
     * @param where the annotated element, named in the error message
     * @throws IllegalArgumentException if an OR group has an empty alternative
     */
    public static void validate(String[] tags, String where) {
        if (tags == null) {
            return;
        }
        for (String tag : tags) {
            if (tag != null && tag.indexOf('|') >= 0) {
                alternatives(tag, where);
            }
        }
    }

    private static List<String> alternatives(String tag, String where) {
        String body = tag.trim();
        if (body.length() >= 2 && body.charAt(0) == '(' && body.charAt(body.length() - 1) == ')') {
            body = body.substring(1, body.length() - 1);
        }
        List<String> group = new ArrayList<>();
        // limit -1 keeps trailing empty strings so "a|" is seen as malformed.
        for (String alternative : body.split("\\|", -1)) {
            String trimmed = alternative.trim();
            if (trimmed.isEmpty()) {
                throw new IllegalArgumentException("Invalid tag '" + tag + "'"
                    + (where != null ? " on " + where : "")
                    + ": each '|' must separate two non-empty alternatives.");
            }
            group.add(trimmed);
        }
        return group;
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
