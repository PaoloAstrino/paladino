"""
LLM Manager - Wrapper for local Ollama API.
"""

import requests
import json
import re
import time
from typing import Dict, Any, Optional
from loguru import logger
from paladino.config import settings
from paladino.errors import (
    llm_offline_error,
    llm_rate_limit_error,
    llm_bad_response_error,
    LLMError,
)


class LLMManager:
    """Manages interactions with Ollama or OpenAI-compatible APIs."""
    
    def __init__(
        self, 
        model: Optional[str] = None, 
        base_url: Optional[str] = None,
        api_key: Optional[str] = None
    ):
        """
        Initialize LLM manager.
        """
        self.model = model or settings.llm_model
        self.api_key = api_key or settings.llm_api_key
        
        # Determine base URL and endpoint
        raw_url = base_url or settings.llm_api_base or settings.ollama_base_url
        if self.api_key:
            # External API (OpenAI/Groq style)
            self.base_url = f"{raw_url.rstrip('/')}/chat/completions"
        else:
            # Local Ollama
            self.base_url = f"{raw_url.rstrip('/')}/api/chat"
    
    def chat(self, messages: list, format: Optional[str] = None, _retry: int = 3) -> str:
        """
        Send a chat request to the LLM (Ollama or API).
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'
            format: Response format ('json' for structured output)
            _retry: Internal retry counter for rate-limit backoff (do not set manually)
            
        Returns:
            Response text from the LLM

        Raises:
            LLMConnectionError: If the LLM service is not reachable.
            LLMRateLimitError: If the API returns HTTP 429 and retries are exhausted.
            LLMBadResponseError: If the response body cannot be parsed.
            LLMError: For any other LLM-side failure.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False
        }
        
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            if format == "json":
                payload["response_format"] = {"type": "json_object"}
        else:
            if format == "json":
                payload["format"] = "json"
            
        try:
            response = requests.post(
                self.base_url, 
                json=payload, 
                headers=headers,
                timeout=180
            )

            # ── rate limit: exponential backoff up to _retry times ──────────
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 0))
                if _retry > 0:
                    wait = retry_after or (2 ** (3 - _retry) * 2)
                    logger.warning(f"LLM rate-limited (429). Retrying in {wait}s ({_retry} attempts left)…")
                    time.sleep(wait)
                    return self.chat(messages, format=format, _retry=_retry - 1)
                raise llm_rate_limit_error(retry_after=retry_after)

            response.raise_for_status()

            # ── parse response ───────────────────────────────────────────────
            try:
                data = response.json()
            except (ValueError, json.JSONDecodeError) as parse_err:
                raise llm_bad_response_error(raw=response.text) from parse_err
            
            # Navigate different response structures
            if "choices" in data:
                content = data["choices"][0]["message"]["content"]
            else:
                content = data.get("message", {}).get("content", "")

            if not isinstance(content, str):
                raise llm_bad_response_error(raw=str(data))

            return content
            
        except requests.exceptions.ConnectionError as e:
            raise llm_offline_error(url=self.base_url, original=e) from e
        except requests.exceptions.Timeout as e:
            raise LLMError(
                message=f"⏱️  LLM request timed out after 180 s.",
                hint="The model may be loading or the prompt is very long. Try again.",
            ) from e
        except LLMError:
            raise
        except requests.RequestException as e:
            logger.error(f"LLM API call failed: {e}")
            raise LLMError(message=f"LLM API call failed: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error in LLM chat: {e}")
            raise

    def classify_intent(self, question: str, available_templates: list) -> Dict[str, Any]:
        """
        Classify natural language question into a Cypher template.

        Args:
            question: Natural language question from user
            available_templates: List of valid template names to choose from

        Returns:
            Dictionary with 'template_name' and 'params' keys.
            Returns {'template_name': None, 'params': {}} on failure.
        """
        system_prompt = (
            "You are an expert intent classifier for a Knowledge Graph about Italian public procurement. "
            "Map the user question to ONE of the available Cypher templates ONLY if it is a clear, "
            "confident match. If the question is vague, off-topic, ambiguous, or does not map "
            "well to any template, set template_name to null. "
            f"Available templates: {', '.join(available_templates)}. "
            "Return ONLY a valid JSON object with exactly these keys: "
            "'template_name' (string or null), 'params' (object - must be a dict/object, not string or null), "
            "'confidence' (float 0.0-1.0 — how confident you are this template fits the question). "
            "Example: {\"template_name\": null, \"params\": {}, \"confidence\": 0.3} "
            "Set confidence below 0.7 and template_name to null for unclear questions. "
            "NEVER wrap the JSON in markdown code blocks or any other formatting."
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question}
        ]
        
        response_text = self.chat(messages, format="json")
        
        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError:
            logger.warning(f"classify_intent: LLM response is not valid JSON: {response_text[:200]}")
            return {"template_name": None, "params": {}}

        # Validate expected structure
        if not isinstance(parsed, dict):
            logger.warning(f"classify_intent: expected dict, got {type(parsed).__name__}")
            return {"template_name": None, "params": {}}

        template_name = parsed.get("template_name")
        params = parsed.get("params", {})
        confidence = parsed.get("confidence", 1.0)

        # Ensure params is always a dict
        if not isinstance(params, dict):
            logger.warning(f"classify_intent: 'params' is {type(params).__name__}, converting to dict")
            params = {}

        # Reject low-confidence matches — let dynamic Cypher generation handle them.
        CONFIDENCE_THRESHOLD = 0.7
        if template_name and (not isinstance(confidence, (int, float)) or confidence < CONFIDENCE_THRESHOLD):
            logger.info(
                f"classify_intent: template '{template_name}' rejected "
                f"(confidence={confidence} < {CONFIDENCE_THRESHOLD})"
            )
            template_name = None

        return {"template_name": template_name, "params": params}

    def generate_cypher(self, question: str, schema_metadata: str) -> Optional[str]:
        """
        Generate a Cypher query from natural language using schema context.

        Security: Only READ-ONLY queries are allowed. Write operations are blocked.
        Uses regex with word boundaries to prevent obfuscation bypasses.
        
        Args:
            question: Natural language question from user
            schema_metadata: Database schema description for context
            
        Returns:
            Validated Cypher query string, or None if security check fails
        """
        system_prompt = (
            "You are a Neo4j Cypher expert. Given the following database schema, "
            "generate a READ-ONLY Cypher query to answer the user's question. "
            "Return ONLY the Cypher query string, no explanation. "
            "IMPORTANT: Only use MATCH, RETURN, WHERE, ORDER BY, LIMIT, WITH, OPTIONAL MATCH. "
            "Do NOT use any write operations. "
            f"Schema:\n{schema_metadata}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question}
        ]

        cypher = self.chat(messages).strip()

        # Delegate to the shared security gate
        return self._cypher_security_check(cypher, logger)

    def fix_cypher(self, failed_query: str, error: str, schema_metadata: str) -> Optional[str]:
        """Generate a corrected Cypher query based on a failure message.

        The fixed query is passed through the same security checks as ``generate_cypher``.
        """
        system_prompt = (
            "You are a Neo4j Cypher expert. A previous query failed. "
            "Analyze the error, consult the schema, and provide a FIXED version of the query. "
            "Return ONLY the Cypher query string, no explanation.\n"
            f"Schema:\n{schema_metadata}"
        )
        
        user_msg = (
            f"Failed Query: {failed_query}\n"
            f"Error Message: {error}\n"
            "Please provide the corrected Cypher query."
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg}
        ]
        
        fixed = self.chat(messages).strip()
        # Re-run the same security gate so a jailbroken model cannot sneak in writes
        return self._cypher_security_check(fixed, logger)

    # ── internal shared security check callable ──────────────────────────────
    @staticmethod
    def _cypher_security_check(cypher: str, log) -> Optional[str]:
        """Return the cypher if it passes all write-op checks, else None."""
        # Strip markdown code block wrapping if present (LLMs may wrap in ```)
        cypher = cypher.strip()
        if cypher.startswith('```'):
            # Remove opening ``` (and optional language specifier like ```cypher)
            cypher = re.sub(r'^\s*```(?:cypher)?\s*\n?', '', cypher, flags=re.MULTILINE)
            # Remove closing ```
            cypher = re.sub(r'\n?\s*```\s*$', '', cypher)
            cypher = cypher.strip()
        
        forbidden_patterns = [
            (r'\bDELETE\b', 'DELETE operation'),
            (r'\bDETACH\b', 'DETACH operation'),
            (r'\bREMOVE\b', 'REMOVE operation'),
            (r'\bDROP\b', 'DROP operation'),
            (r'\bCREATE\b', 'CREATE operation'),
            (r'\bMERGE\b', 'MERGE operation'),
            (r'\bSET\b', 'SET operation'),
            (r'\bapoc\.do\.write\b', 'APOC write procedure'),
            (r'\bapoc\.create\b', 'APOC create procedure'),
            (r'\bapoc\.merge\b', 'APOC merge procedure'),
            (r'\bapoc\.set\b', 'APOC set procedure'),
            (r'\bapoc\.delete\b', 'APOC delete procedure'),
            (r'\bCREATE\s+CONSTRAINT\b', 'CREATE CONSTRAINT'),
            (r'\bDROP\s+CONSTRAINT\b', 'DROP CONSTRAINT'),
            (r'\bCREATE\s+INDEX\b', 'CREATE INDEX'),
            (r'\bDROP\s+INDEX\b', 'DROP INDEX'),
        ]
        for pattern, description in forbidden_patterns:
            if re.search(pattern, cypher, re.IGNORECASE):
                log.warning(f"Blocked {description}: {cypher[:100]}...")
                return None
        read_only_starts = ["MATCH", "CALL", "WITH", "RETURN"]
        if not any(cypher.strip().upper().startswith(kw) for kw in read_only_starts):
            log.warning(f"Blocked Cypher query with suspicious start: {cypher[:100]}...")
            return None
        return cypher
