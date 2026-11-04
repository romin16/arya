# ARYA browser frontend

Serve this folder from the repository root in PowerShell:

```powershell
.\scripts\serve_frontend.ps1
```

Then open <http://localhost:8080>. The script runs Python's static HTTP server
bound to localhost on port 8080.

## Optional Picovoice wake word

1. Create or sign in to an account at the [Picovoice Console](https://console.picovoice.ai/)
   and copy your AccessKey from the console. Keep it private.
2. In the Console's Porcupine area, train a custom wake word and download the
   keyword model for **Web (WASM)**. Put its `.ppn` file in this folder. The
   page currently expects `hey-arya_en_wasm_v4_0_0.ppn`; rename your downloaded
   Web model to that name, or update `PPN_FILE` in `arya.html`.
3. Copy the example config and edit the local copy:

   ```powershell
   Copy-Item frontend/config.local.example.js frontend/config.local.js
   notepad frontend/config.local.js
   ```

   Replace `YOUR_PORCUPINE_ACCESS_KEY` with your AccessKey. `config.local.js`
   and `.ppn` files are ignored by Git. Never commit either one.
4. Reload the page. If no AccessKey is configured, the page falls back to the
   browser's Web Speech wake-word recognition where supported.

Picovoice's [Porcupine Web quick start](https://picovoice.ai/docs/quick-start/porcupine-web/)
documents AccessKeys and Web (WASM) keyword models.
