/**
 * Opt-in strict dependency-injection diagnostics (`MCP_MESH_STRICT_DI`).
 *
 * Mirrors the Python runtime's `_mcp_mesh/engine/strict_di.py`: DI
 * parameter-selection diagnostics are warnings by default and the agent keeps
 * running. Setting `MCP_MESH_STRICT_DI` to a truthy value promotes exactly
 * that ambiguity/skip class of warnings to a {@link StrictDIError} at
 * registration time — the error text is identical to the warning text, so
 * the fix instructions travel with the failure.
 *
 * Injection SEMANTICS are untouched in both modes: dependencies pair with
 * `execute` parameters positionally by declaration order. Strict mode only
 * changes warn-vs-raise for the diagnostic.
 */

/** A DI ambiguity/skip diagnostic promoted to an error by strict mode. */
export class StrictDIError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "StrictDIError";
  }
}

// Strict mode is a process-level posture, resolved once (same as Python).
let strictDiEnabled: boolean | null = null;

/**
 * Parse a boolean env value with Python's `ValidationRule.TRUTHY_RULE`
 * vocabulary: `true/1/yes/on` and `false/0/no/off`, case-insensitive. Any
 * other value is reported and falls back to `defaultValue`.
 */
function parseTruthyEnv(name: string, defaultValue: boolean): boolean {
  const raw = process.env[name];
  if (raw === undefined) return defaultValue;
  const lower = raw.toLowerCase();
  if (["true", "1", "yes", "on"].includes(lower)) return true;
  if (["false", "0", "no", "off"].includes(lower)) return false;
  console.error(
    `Config validation failed for ${name}: ${name} must be a boolean value ` +
      `(true/false, 1/0, yes/no, on/off), got '${raw}'`,
  );
  return defaultValue;
}

/** True when `MCP_MESH_STRICT_DI` resolves truthy. Cached per process. */
export function isStrictDiEnabled(): boolean {
  if (strictDiEnabled === null) {
    strictDiEnabled = parseTruthyEnv("MCP_MESH_STRICT_DI", false);
  }
  return strictDiEnabled;
}

/** Drop the cached env resolution (test support only). */
export function __resetStrictDiCacheForTests(): void {
  strictDiEnabled = null;
}

/** `"1 dependency"`, `"3 dependencies"`, `"0 parameters"`. */
export function pluralize(count: number, singular: string, plural?: string): string {
  const noun = count === 1 ? singular : (plural ?? `${singular}s`);
  return `${count} ${noun}`;
}

/**
 * Emit `message` as a warning, or throw {@link StrictDIError} under strict
 * mode. Single choke point so the warning and error text cannot drift.
 */
export function warnOrRaise(message: string): void {
  if (isStrictDiEnabled()) {
    throw new StrictDIError(message);
  }
  console.warn(message);
}

/**
 * The declared parameter list of a function, read from its source text.
 *
 * `Function.length` cannot answer the arity question: it stops counting at
 * the first default-valued or rest parameter, so `(args, dep = null)` and
 * `(args, ...deps)` both report 1. This scans the parameter list with
 * bracket/string awareness and returns the top-level parameter texts, or
 * `null` when the count is unbounded (a rest parameter) or unknowable
 * (native/bound function, unparseable source). Callers must treat `null` as
 * "skip the check" — the diagnostic never guesses.
 *
 * Under `MCP_MESH_STRICT_DI` a false positive is a boot failure, so every
 * uncertainty returns `null` rather than a low count:
 *   - the source references `arguments` (ES5/Babel/SWC down-levelled rest or
 *     default parameters, `fn.apply(this, arguments)` wrappers);
 *   - the scanned count is below `fn.length` (the source disagrees with the
 *     engine);
 *   - the parameter list holds a `/` outside a string or comment (a possible
 *     regex literal) or a template literal with a `${` substitution;
 *   - the text before the first `(` holds `[` or a quote (computed or
 *     string-literal method key, where that `(` may not open the list).
 * A minifier that drops unused trailing parameters (terser
 * `keep_fargs: false`) cannot be detected from the source; that limit is
 * documented on the DI pages.
 */
export function declaredParameters(fn: Function): string[] | null {
  let src: string;
  try {
    src = Function.prototype.toString.call(fn);
  } catch {
    return null;
  }
  if (src.includes("[native code]")) return null;
  // A class's first `(` belongs to a member, not to a call signature.
  if (/^\s*class\b/.test(src)) return null;
  // Down-levelled rest/default params and forwarding wrappers read their
  // inputs through `arguments`; their declared list says nothing.
  if (/\barguments\b/.test(src)) return null;

  const params = scanParameterList(src);
  if (params === null) return null;
  if (params.length < fn.length) return null;
  return params;
}

function scanParameterList(src: string): string[] | null {
  // Single-identifier arrow: `x => ...` / `async x => ...`.
  const bareArrow = /^\s*(?:async\s+)?([A-Za-z_$][\w$]*)\s*=>/.exec(src);
  if (bareArrow) return [bareArrow[1]];

  const open = src.indexOf("(");
  if (open < 0) return null;
  // Computed (`[Symbol.for("x")](...)`) or string-literal (`"a(b"(...)`)
  // method keys: the first `(` may not open the parameter list.
  if (/[[\]"'`]/.test(src.slice(0, open))) return null;

  const params: string[] = [];
  let depth = 0;
  let current = "";
  let i = open + 1;
  for (; i < src.length; i++) {
    const ch = src[i];
    if (ch === '"' || ch === "'" || ch === "`") {
      const end = skipString(src, i);
      if (end < 0) return null;
      const literal = src.slice(i, end + 1);
      // A template substitution can nest anything, quotes and backticks
      // included; this lexer does not follow it.
      if (ch === "`" && literal.includes("${")) return null;
      current += literal;
      i = end;
      continue;
    }
    if (ch === "/" && src[i + 1] === "/") {
      const nl = src.indexOf("\n", i);
      if (nl < 0) return null;
      i = nl;
      continue;
    }
    if (ch === "/" && src[i + 1] === "*") {
      const close = src.indexOf("*/", i + 2);
      if (close < 0) return null;
      i = close + 1;
      continue;
    }
    // Any other `/` may start a regex literal whose brackets would derail
    // the depth count. Bail out rather than guess.
    if (ch === "/") return null;
    if (ch === "(" || ch === "[" || ch === "{") depth++;
    else if (ch === ")" || ch === "]" || ch === "}") {
      if (depth === 0) {
        if (ch !== ")") return null;
        break;
      }
      depth--;
    } else if (ch === "," && depth === 0) {
      params.push(current.trim());
      current = "";
      continue;
    }
    current += ch;
  }
  if (i >= src.length) return null;
  const last = current.trim();
  if (last.length > 0) params.push(last);
  if (params.some((p) => p.length === 0 || p.startsWith("..."))) return null;
  return params;
}

function skipString(src: string, start: number): number {
  const quote = src[start];
  for (let j = start + 1; j < src.length; j++) {
    if (src[j] === "\\") {
      j++;
      continue;
    }
    if (src[j] === quote) return j;
  }
  return -1;
}

/** A parameter's binding text without its default value (`dep = null` → `dep`). */
export function parameterLabel(param: string): string {
  let depth = 0;
  for (let i = 0; i < param.length; i++) {
    const ch = param[i];
    if (ch === "(" || ch === "[" || ch === "{") depth++;
    else if (ch === ")" || ch === "]" || ch === "}") depth--;
    else if (ch === "=" && depth === 0 && param[i + 1] !== ">") {
      return param.slice(0, i).trim();
    }
  }
  return param.trim();
}
