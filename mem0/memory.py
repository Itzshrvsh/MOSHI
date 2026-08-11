import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
import moshi_config

from mem0 import Memory


config = {
    "llm": {
        "provider": "lmstudio",
        "config": {
            "model": moshi_config.get_model(),
            "temperature": 0.0,
            "max_tokens": 2000,
            "lmstudio_base_url": "http://localhost:1234/v1",

            # LM Studio does not accept Mem0's default
            # {"type": "json_object"} format.
            "lmstudio_response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "memory_extraction",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "memory": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {
                                            "type": "string"
                                        },
                                        "text": {
                                            "type": "string"
                                        },
                                        "attributed_to": {
                                            "type": "string"
                                        }
                                    },
                                    "required": [
                                        "id",
                                        "text",
                                        "attributed_to"
                                    ]
                                }
                            }
                        },
                        "required": [
                            "memory"
                        ]
                    }
                }
            },
        },
    },

    "embedder": {
        "provider": "lmstudio",
        "config": {
            "model": "text-embedding-nomic-embed-text-v1.5",
            "embedding_dims": 768,
            "lmstudio_base_url": "http://localhost:1234/v1",
        },
    },

    "vector_store": {
        "provider": "qdrant",
        "config": {
            "collection_name": "moshi_memory",
            "host": "localhost",
            "port": 6333,
            "embedding_model_dims": 768,
        },
    },
}


memory = Memory.from_config(config)