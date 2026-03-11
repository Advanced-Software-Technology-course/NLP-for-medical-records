
# Quick setup guide

## 0. Prerequisites

- Python 3.8+
- `pip install openai`
- `pip install requests`
- Alternatively: `pip install -r requirements.txt`
- The `.api_token.json` file in the root of the project (see bottom of this guide)

## 1. Groq (Summarization)

1. Go to [console.groq.com](https://console.groq.com/)
2. Sign up or log in
3. Find in the upper right corner and click **API Keys**
4. Click **Create API Key**
5. Give it a name (e.g. `nlp-medical-dev`)
6. Copy the key to somewhere temporarily, keep in mind **you won't be able to see it again!**

## 2. Gladia (Transcription + Diarization)

1. Go to [app.gladia.io](https://app.gladia.io/)
2. Sign up or log in
3. You will find one API key on the main page
4. Copy the key to somewhere temporarily

## 4. Setting Up `.api_token.json`

Create a file called `.api_token.json` in the **root of the project folder**, and then paste the tokens you've gotten from before.

```json
{
  "groq-token": "your_groq_key_here",
  "gladia-token": "your_gladia_key_here"
}
```

**Never commit this file to GitHub.** Make sure `.api_token.json` is listed in your `.gitignore` file (this is the file that tells git to not push certain files up):

## 5. Running the Pipeline

1. Open your command line.
2. Navigate to pipeline/
3. Run any of these:

```bash
# From an audio file
python medical_pipeline.py --audio test_audio.mp3

# From an existing transcript text file
python medical_pipeline.py --transcript test_transcript_en.txt

# Specify a custom output file
python medical_pipeline.py --audio test_audio.mp3 --output my_output.json

# Default run, will automatically run from audio transcription
python medical_pipeline.py

```

Output is saved as a `.json` file containing the transcript, summary, and SOAP note in the root folder.