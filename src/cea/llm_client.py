"""
LLM 클라이언트 추상화 레이어.
Ollama / Groq / Anthropic 중 어떤 백엔드를 쓰든 동일한 인터페이스로 호출.
"""
from __future__ import annotations


def create_client(backend: str, api_key: str | None = None):
    """backend: 'ollama' | 'groq' | 'anthropic'"""
    if backend == "ollama":
        from openai import OpenAI
        return OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

    if backend == "groq":
        from openai import OpenAI
        return OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)

    if backend == "anthropic":
        import anthropic
        return anthropic.Anthropic(api_key=api_key)

    raise ValueError(f"Unknown LLM backend: {backend!r}")


def call_llm(client, model: str, system: str, user: str, max_tokens: int) -> str:
    """백엔드에 관계없이 동일한 방식으로 LLM 호출. 텍스트 응답 반환."""
    # OpenAI 호환 (Ollama / Groq)
    try:
        from openai import OpenAI
        if isinstance(client, OpenAI):
            resp = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return resp.choices[0].message.content.strip()
    except ImportError:
        pass

    # Anthropic
    import anthropic
    if isinstance(client, anthropic.Anthropic):
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text.strip()

    raise TypeError(f"Unsupported client type: {type(client)}")
