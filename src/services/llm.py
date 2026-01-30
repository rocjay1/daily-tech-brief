"""
LLM Service Module.

This module provides the LLMService class, which interfaces with the Google Gemini API
to analyze and curate technical articles based on specific user personas and interests.
"""

import json

import logging
from typing import List, Any, Optional
from google import genai
from src.models import Article

logger = logging.getLogger(__name__)


class LLMService:
    """
    Service for interacting with the Google Gemini API.

    This class handles the initialization of the Gemini client and provides methods
    to analyze and curate technical articles based on defined personas and criteria.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client: Optional[genai.Client] = None
        try:
            self.client = genai.Client(api_key=api_key)
        except Exception as e:
            logger.error("Failed to initialize Gemini client: %s", e)
            self.client = None

    _SYSTEM_PROMPT = """
        You are a Principal Cloud Architect and AI Engineer acting as an intelligent assistant for a Corporate IT System Engineer.

        User Persona:
        - Role: Internal Corporate IT System Engineer at a tech company.
        - Core Stack: Microsoft Azure, Terraform, Python, GitHub Actions.
        - Primary Work: Cloud-native hosting (Websites, Serverless, Storage, Networking).
        - Recent Focus: AI Engineering (Deploying LLM endpoints, configuring AuthN/AuthZ for developer access).
        - Context: Recently migrated from GitLab to GitHub.

        Task: Review the provided RSS headlines and curate the Top {limit} most relevant articles.

        Selection Criteria:
        1. **High Priority (Must Have)**:
        - Architectural patterns for deploying and securing LLMs/AI endpoints on Azure.
        - Advanced Terraform patterns (Azure provider, state management, modules).
        - GitHub Actions security hardening and reusable workflows.
        - Azure networking deep dives (Private Link, DNS, Hub-and-Spoke topology).
        2. **Educational (Good to Have)**:
        - Cloud-native identity patterns (OIDC, OAuth, Workload Identity).
        - Python automation best practices for extensive cloud environments.
        3. **Ignore**:
        - Generic consumer tech news, product marketing fluff, basic "Hello World" tutorials, or GitLab-specific content.

        Input Data:
        {items_str}

        Output Format:
        - Return a raw JSON list of objects.
        - DO NOT use Markdown formatting (no ```json blocks).
        - Object schema: {{"id": int, "analysis": "1 sentence architectural justification"}}
        """

    def _parse_json_response(self, text: str) -> Any:
        """Safely parses JSON from LLM output, handling markdown blocks."""
        cleaned = text.strip()
        # Strip Markdown code blocks usually returned by Gemini
        if cleaned.startswith("```"):
            # Remove opening ```json or ```
            cleaned = cleaned.split("\n", 1)[1]
            # Remove closing ```
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("\n", 1)[0]

        return json.loads(cleaned)

    def _get_gemini_prompt(self, items_str: str, limit: int) -> str:
        """Returns the prompt for Gemini analysis."""
        return self._SYSTEM_PROMPT.format(limit=limit, items_str=items_str)

    def analyze_with_gemini(self, articles: List[Article], limit: int) -> List[Article]:
        """Uses Google Gemini to select the best articles."""
        if not self.client:
            logger.error("Gemini client not initialized.")
            return []

        logger.info("Asking Gemini to curate (limit %d)...", limit)
        # Pre-filter: Increased to 500 to leverage Gemini 2.0 Flash context window
        candidates = articles[:500]

        items_str = json.dumps(
            [
                {"id": i, "source": a["source"], "text": a["full_text"]}
                for i, a in enumerate(candidates)
            ]
        )

        prompt = self._get_gemini_prompt(items_str, limit)

        try:
            response = self.client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            # Use robust parser
            response_text = response.text if response.text else ""
            selections = self._parse_json_response(response_text)

            final_list = []
            for sel in selections:
                if (
                    isinstance(sel, dict)
                    and "id" in sel
                    and sel["id"] < len(candidates)
                ):
                    original = candidates[sel["id"]]
                    original["reason"] = sel.get("analysis", "No analysis provided.")
                    final_list.append(original)
            return final_list

        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Failed to parse Gemini response: %s", e)
            return []
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Gemini API error: %s", e)
            return []
