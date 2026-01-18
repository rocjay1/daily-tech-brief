# System Architecture

## Logic Flow

1. **Fetch:** Python script pulls RSS feeds from Azure, Latent Space, Julia Evans, etc.
2. **Deduplicate:** Checks article URLs against a Firestore database. If it's been seen before, it's skipped.
3. **Analyze:** Sends candidates to Gemini 2.0 Flash to pick the top 15 "High Signal" articles and explain *why* they matter. If the AI processing fails, the workflow stops.
4. **Send:** Formats the chosen articles into an HTML email and sends it via SMTP.
5. **Save:** Writes the new article IDs to Firestore so they aren't sent again tomorrow.
