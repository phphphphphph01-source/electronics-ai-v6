BATA2 - Vision Scan Fix

This patch keeps the existing YOLO + CLIP pipeline, but adds a multimodal Vision stage as the PRIMARY scanner when OPENAI_API_KEY is configured.

What changed:
- app.py sends the uploaded image directly to the OpenAI Responses API as an input_image.
- Vision is asked to identify only one of the project's existing CLASSES.
- Vision can return multiple visible components.
- If Vision is unavailable/uncertain, the existing local YOLO and CLIP fallbacks remain active.
- No dataset labels are fabricated or changed.

Windows PowerShell (current terminal only):
  $env:OPENAI_API_KEY="YOUR_API_KEY"
  $env:ELECTRONICS_AI_VISION_MODEL="gpt-5.6-luna"
  .\run_windows.bat

If your batch file needs the explicit current-directory form:
  .\run_windows.bat

Security:
- Do NOT put the API key into app.py, HTML, JavaScript, Git, or the ZIP.
- Prefer an environment variable. The server sends the image to the configured Vision API only when the key exists.

If OPENAI_API_KEY is not set, the app continues using its existing local AI models.
