/**
 * The tokenizer of the embedding model (Specification 0.1, section 6): BERT's WordPiece, as the
 * pinned `tokenizer.json` describes it, so the page turns a query into the same token ids as the
 * builder's tokenizer.
 *
 * 1. Normalise (BertNormalizer, lowercase, accents stripped as lowercasing implies): drop NUL,
 *    U+FFFD and other characters (Unicode category C) except tab, newline and carriage return;
 *    read white space as a space; put spaces around CJK ideographs; decompose (NFD) and drop
 *    non-spacing marks; lowercase each character on its own.
 * 2. Split (BertPreTokenizer) at white space, which is dropped, and around each punctuation
 *    character (ASCII punctuation or Unicode category P), which is kept as a word.
 * 3. WordPiece: each word becomes its longest vocabulary prefix, then `##`-prefixed longest
 *    pieces of the rest; a word with no such split, or longer than the model's
 *    `max_input_chars_per_word`, is the unknown token.
 * 0. Before all of this, the text is split at the added tokens of `tokenizer.json` (`[CLS]`,
 *    `[SEP]`, `[UNK]`, `[MASK]`, `[PAD]`), matched exactly as written, leftmost and longest
 *    first: each becomes its own id, and only the text between them goes through steps 1 to 3.
 * 4. `[CLS]` first and `[SEP]` last, and at most `maxTokens` ids in all, special tokens counted
 *    (the builder truncates the same way, answer on #105).
 *
 * Any other kind of `tokenizer.json` is refused: the kit implements this one model's tokenizer.
 */

export class TokenizerError extends Error {
  override readonly name = "TokenizerError";
}

const CJK: readonly [number, number][] = [
  [0x4e00, 0x9fff],
  [0x3400, 0x4dbf],
  [0x20000, 0x2a6df],
  [0x2a700, 0x2b73f],
  [0x2b740, 0x2b81f],
  [0x2b920, 0x2ceaf],
  [0xf900, 0xfaff],
  [0x2f800, 0x2fa1f],
];

/** Unicode White_Space, which Rust's `char::is_whitespace` tests. */
const WHITE_SPACE = /[\t\n\v\f\r \u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/u;
const OTHER = /\p{C}/u;
const PUNCTUATION = /[!-/:-@[-`{-~]|\p{P}/u;
const NONSPACING_MARK = /\p{Mn}/gu;

function isCjk(c: string): boolean {
  const code = c.codePointAt(0)!;
  return CJK.some(([lo, hi]) => code >= lo && code <= hi);
}

/** Step 1: the normalised text. */
export function normalise(text: string): string {
  let out = "";
  for (const c of text) {
    if (c === "\u0000" || c === "\ufffd") continue;
    if (c !== "\t" && c !== "\n" && c !== "\r" && OTHER.test(c)) continue;
    if (WHITE_SPACE.test(c)) out += " ";
    else if (isCjk(c)) out += ` ${c} `;
    else out += c;
  }
  const stripped = out.normalize("NFD").replace(NONSPACING_MARK, "");
  let lower = "";
  for (const c of stripped) lower += c.toLowerCase();
  return lower;
}

/** Step 2: the words of normalised text. */
export function words(normalised: string): string[] {
  const out: string[] = [];
  let word = "";
  for (const c of normalised) {
    if (WHITE_SPACE.test(c)) {
      if (word !== "") out.push(word);
      word = "";
    } else if (PUNCTUATION.test(c)) {
      if (word !== "") out.push(word);
      out.push(c);
      word = "";
    } else {
      word += c;
    }
  }
  if (word !== "") out.push(word);
  return out;
}

interface TokenizerJson {
  normalizer?: { type?: string; lowercase?: boolean; strip_accents?: boolean | null; clean_text?: boolean; handle_chinese_chars?: boolean };
  pre_tokenizer?: { type?: string };
  model?: {
    type?: string;
    vocab?: Record<string, number>;
    unk_token?: string;
    continuing_subword_prefix?: string;
    max_input_chars_per_word?: number;
  };
  post_processor?: { type?: string; special_tokens?: Record<string, { ids?: number[] }> };
  added_tokens?: { id?: number; content?: string; normalized?: boolean; single_word?: boolean; lstrip?: boolean; rstrip?: boolean }[];
}

/** `text` with every regular-expression character escaped. */
const escaped = (text: string): string => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export class WordPiece {
  private readonly vocab: Map<string, number>;
  private readonly unk: number;
  private readonly cls: number;
  private readonly sep: number;
  private readonly prefix: string;
  private readonly maxChars: number;
  /** The added tokens by their text, and a pattern that finds them, leftmost and longest first. */
  private readonly added: Map<string, number>;
  private readonly addedPattern: RegExp | undefined;

  /** The tokenizer `json` describes (the text of `tokenizer.json`), or a {@link TokenizerError}. */
  constructor(json: string) {
    let t: TokenizerJson;
    try {
      t = JSON.parse(json) as TokenizerJson;
    } catch (e) {
      throw new TokenizerError(`tokenizer.json is not JSON: ${(e as Error).message}`);
    }
    const n = t.normalizer;
    const supported =
      n?.type === "BertNormalizer" &&
      n.lowercase === true &&
      (n.strip_accents === null || n.strip_accents === undefined || n.strip_accents === true) &&
      n.clean_text === true &&
      n.handle_chinese_chars === true &&
      t.pre_tokenizer?.type === "BertPreTokenizer" &&
      t.model?.type === "WordPiece" &&
      t.post_processor?.type === "TemplateProcessing";
    if (!supported || !t.model?.vocab) {
      throw new TokenizerError("tokenizer.json is not the BERT WordPiece tokenizer of section 6");
    }
    this.vocab = new Map(Object.entries(t.model.vocab));
    const id = (token: string): number => {
      const found = this.vocab.get(token);
      if (found === undefined) throw new TokenizerError(`tokenizer.json has no token ${JSON.stringify(token)}`);
      return found;
    };
    this.unk = id(t.model.unk_token ?? "[UNK]");
    this.cls = id("[CLS]");
    this.sep = id("[SEP]");
    this.prefix = t.model.continuing_subword_prefix ?? "##";
    this.maxChars = t.model.max_input_chars_per_word ?? 100;
    this.added = new Map();
    for (const a of t.added_tokens ?? []) {
      const plain = a.normalized === false && !a.single_word && !a.lstrip && !a.rstrip;
      if (!plain || typeof a.content !== "string" || a.content === "" || !Number.isInteger(a.id)) {
        throw new TokenizerError("tokenizer.json has an added token this kit does not read: only exact, unnormalised ones");
      }
      this.added.set(a.content, a.id!);
    }
    const contents = [...this.added.keys()].sort((a, b) => b.length - a.length || (a < b ? -1 : 1));
    this.addedPattern = contents.length === 0 ? undefined : new RegExp(contents.map(escaped).join("|"), "gu");
  }

  /** Step 3: the ids of one word. */
  private pieces(word: string): number[] {
    const chars = Array.from(word);
    if (chars.length > this.maxChars) return [this.unk];
    const out: number[] = [];
    let start = 0;
    while (start < chars.length) {
      let end = chars.length;
      let found: number | undefined;
      while (start < end) {
        const piece = (start > 0 ? this.prefix : "") + chars.slice(start, end).join("");
        found = this.vocab.get(piece);
        if (found !== undefined) break;
        end -= 1;
      }
      if (found === undefined) return [this.unk];
      out.push(found);
      start = end;
    }
    return out;
  }

  /** The token ids of `text`, `[CLS]` and `[SEP]` included, at most `maxTokens` in all. */
  encode(text: string, maxTokens: number): number[] {
    if (!(Number.isInteger(maxTokens) && maxTokens >= 2)) throw new RangeError("maxTokens must be 2 or more");
    const ids: number[] = [];
    const room = maxTokens - 2;
    const push = (id: number): boolean => {
      if (ids.length === room) return false;
      ids.push(id);
      return true;
    };
    const plain = (segment: string): boolean => {
      for (const word of words(normalise(segment))) for (const id of this.pieces(word)) if (!push(id)) return false;
      return true;
    };
    let at = 0;
    let more = true;
    if (this.addedPattern) {
      for (const match of text.matchAll(this.addedPattern)) {
        more = plain(text.slice(at, match.index)) && push(this.added.get(match[0])!);
        at = match.index + match[0].length;
        if (!more) break;
      }
    }
    if (more) plain(text.slice(at));
    return [this.cls, ...ids, this.sep];
  }
}
