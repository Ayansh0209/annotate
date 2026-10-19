# Build validation

Verified on 19 October 2026 in the supplied Windows workspace.

| Check | Result |
|---|---|
| TypeScript check and Vite production build | Passed |
| Python source compilation | Passed |
| Backend behavior suite | 11 tests passed |
| React interaction suite (Vitest + jsdom) | 5 tests passed |
| Flask-served frontend and bundled assets | HTTP 200 through Flask’s in-process test client |
| Playback endpoint | HTTP Range response verified by backend test |
| Initial practice dataset | Four original clips; no saved annotations or scores |
| Initial real-study dataset | Empty; no invented results |
| Real browser visual/click-through check | Not completed: browser automation failed to initialize |
| Loopback HTTP request from shell | Blocked by environment socket restrictions; server did start |
| Live Gemini caption/judge | Not tested: no API key supplied |
| Live Wikimedia collection | Not tested: external DNS/network access blocked |

The tests exercise separate temporary databases and DOM fixtures. Their example scores are test inputs, never résumé/study metrics. The four bundled practice clips are synthetic procedural media, not public-data research results.

Dependencies for this build were restored from local package caches because registry downloads were blocked. The project keeps exact direct JavaScript package versions in `package.json`; a fresh connected `npm install` resolves the dependency tree and generates a normal lockfile. Python dependencies are installed from `requirements.txt` during setup. The local server used Flask’s development-server fallback because Waitress was not cached; fresh setup installs Waitress.

## Test commands

```sh
npm run build
npm run test:ui
python -m unittest discover -s tests -v
```

For real verification after configuring Gemini, generate one caption from the actual clip, score it yourself, run the judge, then verify both model attribution and evidence rationale. For a study, complete both human passes and inspect the downloaded records. None of those human study steps has been performed by the build agent.
