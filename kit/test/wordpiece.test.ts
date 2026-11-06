// M2.8: the query tokenizer (section 6), on an invented vocabulary: the same steps as the pinned
// `tokenizer.json` (BertNormalizer, BertPreTokenizer, WordPiece, [CLS] … [SEP]). The real
// tokenizer is checked against the builder's ids in `test/model/` (slow).
import { describe, expect, it } from "vitest";
import { TokenizerError, WordPiece, normalise, words } from "../src/index.js";

const VOCAB = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "pump", "##s", "##ing", "un", "##able", "temp", "-", "3", ".", "a", "##b", "温", "度", "cafe", "?"];

const ADDED = ["[PAD]", "[UNK]", "[CLS]", "[SEP]"].map((content) => ({
  id: VOCAB.indexOf(content),
  content,
  single_word: false,
  lstrip: false,
  rstrip: false,
  normalized: false,
  special: true,
}));

function tokenizerJson(overrides: Record<string, unknown> = {}): string {
  return JSON.stringify({
    added_tokens: ADDED,
    normalizer: { type: "BertNormalizer", clean_text: true, handle_chinese_chars: true, strip_accents: null, lowercase: true },
    pre_tokenizer: { type: "BertPreTokenizer" },
    post_processor: { type: "TemplateProcessing" },
    model: {
      type: "WordPiece",
      unk_token: "[UNK]",
      continuing_subword_prefix: "##",
      max_input_chars_per_word: 10,
      vocab: Object.fromEntries(VOCAB.map((t, i) => [t, i])),
    },
    ...overrides,
  });
}

const id = (token: string): number => VOCAB.indexOf(token);
const tokens = (t: WordPiece, text: string, max = 256): string[] => t.encode(text, max).map((i) => VOCAB[i]!);

describe("normalise (BertNormalizer)", () => {
  it("lowercases and strips accents", () => {
    expect(normalise("CAFÉ Crème İ")).toBe("cafe creme i");
  });

  it("reads white space as a space, drops control and format characters, NUL and U+FFFD", () => {
    expect(normalise("a\tb\nc\r\nd e　f")).toBe("a b c  d e f");
    expect(normalise("a\u0000b�c\u0001d​e")).toBe("abcde");
  });

  it("puts spaces around CJK ideographs, not around other scripts", () => {
    expect(normalise("温度ok")).toBe(" 温  度 ok");
    expect(normalise("온도")).toBe(normalise("온도"));
  });
});

describe("words (BertPreTokenizer)", () => {
  it("splits at white space, which is dropped, and around punctuation, which is kept", () => {
    expect(words("temp-3. is a pump?")).toEqual(["temp", "-", "3", ".", "is", "a", "pump", "?"]);
    expect(words("  ")).toEqual([]);
    expect(words("a«b»c")).toEqual(["a", "«", "b", "»", "c"]);
  });
});

describe("WordPiece", () => {
  const t = new WordPiece(tokenizerJson());

  it("wraps the ids in [CLS] and [SEP]", () => {
    expect(t.encode("pump", 256)).toEqual([id("[CLS]"), id("pump"), id("[SEP]")]);
    expect(tokens(t, "")).toEqual(["[CLS]", "[SEP]"]);
  });

  it("splits a word into its longest vocabulary prefix and ## pieces", () => {
    expect(tokens(t, "Pumps pumping unable")).toEqual(["[CLS]", "pump", "##s", "pump", "##ing", "un", "##able", "[SEP]"]);
    expect(tokens(t, "TEMP-3.")).toEqual(["[CLS]", "temp", "-", "3", ".", "[SEP]"]);
    expect(tokens(t, "Café?")).toEqual(["[CLS]", "cafe", "?", "[SEP]"]);
    expect(tokens(t, "温度")).toEqual(["[CLS]", "温", "度", "[SEP]"]);
  });

  it("gives one unknown token for a word with no split, or longer than the model allows", () => {
    expect(tokens(t, "pumpx")).toEqual(["[CLS]", "[UNK]", "[SEP]"]);
    expect(tokens(t, "zzz pump")).toEqual(["[CLS]", "[UNK]", "pump", "[SEP]"]);
    expect(tokens(t, "a" + "b".repeat(9))).toEqual(["[CLS]", "a", ...Array(9).fill("##b"), "[SEP]"]);
    expect(tokens(t, "a" + "b".repeat(10))).toEqual(["[CLS]", "[UNK]", "[SEP]"]);
  });

  it("keeps at most maxTokens ids, [CLS] and [SEP] counted", () => {
    const ids = t.encode("pump ".repeat(300), 256);
    expect(ids).toHaveLength(256);
    expect(ids[0]).toBe(id("[CLS]"));
    expect(ids[255]).toBe(id("[SEP]"));
    expect(tokens(t, "pumps pumps", 4)).toEqual(["[CLS]", "pump", "##s", "[SEP]"]);
    expect(t.encode("pump pump", 4)).toHaveLength(4);
  });

  it("reads an added token written in the text as that token, exactly as written", () => {
    expect(tokens(t, "pump[SEP]pumps [CLS]")).toEqual(["[CLS]", "pump", "[SEP]", "pump", "##s", "[CLS]", "[SEP]"]);
    // Another case, or an unclosed bracket, is plain text: "[", "sep", "]", "[", "sep".
    expect(tokens(t, "[sep] [SEP")).toEqual(["[CLS]", "[UNK]", "[UNK]", "[UNK]", "[UNK]", "[UNK]", "[SEP]"]);
    expect(tokens(t, "[UNK][UNK]", 3)).toEqual(["[CLS]", "[UNK]", "[SEP]"]);
  });

  it("refuses an added token it cannot read exactly", () => {
    const loose = [{ ...ADDED[0], normalized: true }];
    expect(() => new WordPiece(tokenizerJson({ added_tokens: loose }))).toThrow(TokenizerError);
  });

  it("refuses a tokenizer.json of another kind", () => {
    expect(() => new WordPiece("not json")).toThrow(TokenizerError);
    expect(() => new WordPiece(tokenizerJson({ model: { type: "BPE", vocab: {} } }))).toThrow(TokenizerError);
    expect(() => new WordPiece(tokenizerJson({ pre_tokenizer: { type: "Whitespace" } }))).toThrow(TokenizerError);
    expect(
      () =>
        new WordPiece(
          tokenizerJson({ normalizer: { type: "BertNormalizer", clean_text: true, handle_chinese_chars: true, lowercase: false } }),
        ),
    ).toThrow(TokenizerError);
  });
});
