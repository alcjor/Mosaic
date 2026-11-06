// The kit's tests on the real embedding model (Specification 0.1, section 6). The model files
// are not in the repository: `uv run python scripts/fetch_model.py` puts them in
// `.cache/model/`, and the slow test `tests/test_kit_model.py` runs these tests
// (`uv run pytest -m slow`). The fast suite (`bun run test`) does not include them.
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: { include: ["test/model/**/*.model-test.ts"], testTimeout: 300_000 },
});
