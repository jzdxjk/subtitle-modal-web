from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_transcribe_config_endpoint_accepts_all_transcribe_form_fields():
    main_py = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    start = main_py.index("class TranscribeConfigPayload")
    end = main_py.index("@app.post(\"/api/transcribe-config\")")
    payload_block = main_py[start:end]

    for field in (
        "enable_transcribe",
        "openai_api_url",
        "openai_api_key",
        "openai_model",
        "transcribe_prompt",
        "transcribe_model",
    ):
        assert field in payload_block
