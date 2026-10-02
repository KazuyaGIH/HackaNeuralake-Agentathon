"""NeuraLakeAdapter: API OpenAI-compatible (chat/completions) com opcoes de roteamento por capacidade.

Referencia publica (https://www.neuralake.com.br/api): base https://api.neuralake.cloud/v1, `model` em
{auto, text, code, reasoning, reasoning-pro, multimodal}. Chave validada com uma chamada real em 02/10/2026.
Nunca faz fallback para mock, outro modelo ou outro provedor.
"""

from app.providers.openai_compat import OpenAICompatAdapter


class NeuraLakeAdapter(OpenAICompatAdapter):
    name = "neuralake"
    label = "NeuraLake"
    key_env = "AGENTATHON_NEURALAKE_API_KEY"
