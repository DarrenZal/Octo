#!/usr/bin/env python3
"""
LLM Extraction Layer for Web Content Processing

Extracts structured entities, relationships, descriptions, and schema-specific
fields from full source content using Gemini via Google AI Studio API.

This module sits between /web/preview (content fetch) and /web/ingest (resolution + storage).
The /ingest endpoint stays LLM-free — this module handles all LLM work.

Usage:
    result = await extract_from_content(content, title, url)
    # result.entities, result.relationships, result.topics, result.summary
"""

import os
import json
import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Config
LLM_BACKEND = os.getenv("LLM_BACKEND", "gemini")
LLM_ENRICHMENT_ENABLED = os.getenv("LLM_ENRICHMENT_ENABLED", "false").lower() == "true"
LLM_GEMINI_MODEL = os.getenv("LLM_GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
VERTEX_PROJECT_ID = os.getenv("VERTEX_PROJECT_ID", "")
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "us-central1")

# Import schema definitions for prompt construction and validation
from api.entity_schema import DEFAULT_SCHEMAS, FOLDER_FALLBACKS
from api.vault_parser import FIELD_TO_PREDICATE, PREDICATE_TO_FIELD

# Valid predicates (the 27 BKC predicates)
VALID_PREDICATES = set(PREDICATE_TO_FIELD.keys())

# Valid entity types
VALID_ENTITY_TYPES = set(DEFAULT_SCHEMAS.keys())

# Common LLM field name variations → canonical field names
FIELD_NORMALIZATIONS = {
    "headquarters": "location",
    "hq": "location",
    "based_in": "location",
    "based in": "location",
    "members": "people",
    "team": "people",
    "staff": "people",
    "employees": "people",
    "parent_organization": "parentOrg",
    "parent_org": "parentOrg",
    "parent organization": "parentOrg",
    "website": "website",  # not a predicate field, kept as metadata
    "url": "website",
    "expertise": "expertise",  # not a predicate field, kept as metadata
    "role": "role",  # not a predicate field, kept as metadata
    "title": "role",
    "methodology": "methodology",  # metadata
    "outcomes": "outcomes",  # metadata
    "status": "status",  # metadata
    "geographic_scope": "bioregion",
    "geographic scope": "bioregion",
    "region": "bioregion",
    "affiliation": "affiliation",
    "affiliations": "affiliation",
    "organization": "affiliation",
    "organizations": "affiliation",
    "founder": "founder",
    "founded_by": "founders",
    "founded by": "founders",
    "projects": "projects",
}

# Fields that map to predicates (for validation)
PREDICATE_FIELDS = set(FIELD_TO_PREDICATE.keys())


@dataclass
class ExtractedEntityResult:
    """An entity extracted by the LLM."""
    name: str
    type: str
    description: str = ""
    fields: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.9


@dataclass
class ExtractedRelationshipResult:
    """A relationship extracted by the LLM."""
    subject: str
    predicate: str
    object: str
    confidence: float = 0.9


@dataclass
class ExtractionResult:
    """Full extraction result from LLM."""
    entities: List[ExtractedEntityResult] = field(default_factory=list)
    relationships: List[ExtractedRelationshipResult] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    summary: str = ""
    model_used: str = ""
    token_count: int = 0


def _build_extraction_prompt(
    source_content: str,
    source_title: str,
    source_url: str,
    existing_entities: List[dict] = None,
) -> str:
    """Build the extraction prompt with schema context."""

    existing_context = ""
    if existing_entities:
        entity_names = [e.get("name", "") for e in existing_entities[:50]]
        existing_context = f"""
Known entities in the knowledge graph (match against these when possible):
{json.dumps(entity_names, indent=2)}
"""

    return f"""Extract all entities, relationships, and structured fields from this web page.

Source: {source_title}
URL: {source_url}

{existing_context}
Entity types and their expected fields:
- Organization: description, website, location, affiliation (parent orgs), founders (people), projects
- Person: description, affiliation (orgs), expertise, role/title
- Project: description, location, parentOrg, people, status
- Practice: description, bioregion, methodology, outcomes, people
- Concept: description, broader (parent concepts), narrower (child concepts), related_to
- Bioregion: description, geographic scope, ecological features
- Pattern: description, suggests (practices), broader (concepts)
- CaseStudy: description, documents (practices), bioregion
- Protocol: description, implementedBy (playbooks)
- Playbook: description, implements (protocols), bioregion
- Location: description, broader (parent location)
- Question: description, about (concepts/topics)
- Claim: description, supports/opposes (other claims), about
- Evidence: description, supports (claims), about

Valid relationship predicates (use ONLY these):
affiliated_with, located_in, has_founder, involves_person, has_project,
involves_organization, collaborates_with, knows, founded,
aggregates_into, suggests, practiced_in, documents,
supports, opposes, informs, generates, implemented_by, synthesizes, about,
broader, narrower, related_to, forked_from, builds_on, inspired_by

Rules:
1. Extract entities ONLY from the source content below. Do not hallucinate.
2. Every entity MUST have a description (1-3 sentences from the source content).
3. Use the exact predicate names listed above for relationships.
4. Set confidence based on how explicitly the information appears in the source.
5. For the summary, write 2-4 sentences describing what this page is about.
6. For topics, extract 3-8 key themes as short phrases.

Return JSON with this exact structure:
{{
  "entities": [
    {{
      "name": "Entity Name",
      "type": "Organization",
      "description": "1-3 sentence description from source content",
      "fields": {{"website": "https://...", "location": "Place Name"}},
      "confidence": 0.95
    }}
  ],
  "relationships": [
    {{
      "subject": "Entity A",
      "predicate": "affiliated_with",
      "object": "Entity B",
      "confidence": 0.9
    }}
  ],
  "topics": ["topic1", "topic2"],
  "summary": "2-4 sentence summary of the page content"
}}

--- SOURCE CONTENT ---
{source_content}
"""


SYSTEM_PROMPT = """You are a knowledge graph extraction agent for a bioregional knowledge commons focused on the Salish Sea region. You extract structured entities, relationships, and descriptions from web content. You are precise and only extract information that is explicitly present in the source material. You always return valid JSON."""


# Gemini client (lazy-initialized)
_genai_client = None


def _get_genai_client():
    """Lazy-initialize the Google GenAI client (Vertex AI or API key)."""
    global _genai_client
    if _genai_client is None:
        try:
            from google import genai

            if VERTEX_PROJECT_ID:
                _genai_client = genai.Client(
                    vertexai=True,
                    project=VERTEX_PROJECT_ID,
                    location=VERTEX_LOCATION,
                )
                logger.info(f"Initialized Vertex AI client (project: {VERTEX_PROJECT_ID}, "
                           f"location: {VERTEX_LOCATION}, model: {LLM_GEMINI_MODEL})")
            elif GEMINI_API_KEY:
                _genai_client = genai.Client(api_key=GEMINI_API_KEY)
                logger.info(f"Initialized Google GenAI client with API key (model: {LLM_GEMINI_MODEL})")
            else:
                raise ValueError("Set VERTEX_PROJECT_ID for Vertex AI or GEMINI_API_KEY for AI Studio")
        except Exception as e:
            logger.error(f"Failed to initialize Google GenAI client: {e}")
            raise
    return _genai_client


async def _call_gemini(prompt: str) -> str:
    """Call Gemini via Google AI Studio and return the response text."""
    import asyncio
    from google.genai import types

    client = _get_genai_client()

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        temperature=0.3,
    )

    # google-genai SDK is synchronous, run in thread pool
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.models.generate_content(
            model=LLM_GEMINI_MODEL,
            contents=prompt,
            config=config,
        ),
    )

    return response.text


def _validate_entity_type(entity_type: str) -> str:
    """Validate and normalize entity type."""
    if entity_type in VALID_ENTITY_TYPES:
        return entity_type

    # Case-insensitive match
    for valid_type in VALID_ENTITY_TYPES:
        if entity_type.lower() == valid_type.lower():
            return valid_type

    logger.warning(f"Unknown entity type from LLM: '{entity_type}', defaulting to 'Concept'")
    return "Concept"


def _validate_predicate(predicate: str) -> Optional[str]:
    """Validate a relationship predicate against the allowed set."""
    if predicate in VALID_PREDICATES:
        return predicate

    # Try underscore/hyphen normalization
    normalized = predicate.replace("-", "_").replace(" ", "_").lower()
    if normalized in VALID_PREDICATES:
        return normalized

    logger.warning(f"Invalid predicate from LLM: '{predicate}', skipping")
    return None


def _normalize_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize LLM field names to canonical forms."""
    normalized = {}
    for key, value in fields.items():
        canonical = FIELD_NORMALIZATIONS.get(key.lower(), key.lower())
        normalized[canonical] = value
    return normalized


def _parse_extraction_response(response_text: str) -> ExtractionResult:
    """Parse and validate the LLM JSON response."""
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}")
        logger.debug(f"Response text: {response_text[:500]}")
        return ExtractionResult()

    result = ExtractionResult()

    # Parse entities
    for raw_entity in data.get("entities", []):
        entity_type = _validate_entity_type(raw_entity.get("type", "Concept"))
        fields = _normalize_fields(raw_entity.get("fields", {}))

        result.entities.append(ExtractedEntityResult(
            name=raw_entity.get("name", "").strip(),
            type=entity_type,
            description=raw_entity.get("description", "").strip(),
            fields=fields,
            confidence=raw_entity.get("confidence", 0.9),
        ))

    # Parse relationships
    for raw_rel in data.get("relationships", []):
        predicate = _validate_predicate(raw_rel.get("predicate", ""))
        if predicate is None:
            continue

        result.relationships.append(ExtractedRelationshipResult(
            subject=raw_rel.get("subject", "").strip(),
            predicate=predicate,
            object=raw_rel.get("object", "").strip(),
            confidence=raw_rel.get("confidence", 0.9),
        ))

    # Parse topics and summary
    result.topics = [t.strip() for t in data.get("topics", []) if isinstance(t, str)]
    result.summary = data.get("summary", "").strip()

    # Filter out empty entities
    result.entities = [e for e in result.entities if e.name]

    logger.info(f"Parsed extraction: {len(result.entities)} entities, "
                f"{len(result.relationships)} relationships, "
                f"{len(result.topics)} topics")

    return result


async def extract_from_content(
    source_content: str,
    source_title: str,
    source_url: str,
    existing_entities: List[dict] = None,
) -> ExtractionResult:
    """Extract structured entities, relationships, and descriptions from source content.

    Single batched LLM call that extracts everything from one source document.

    Args:
        source_content: Full text content of the source page
        source_title: Page title
        source_url: Page URL
        existing_entities: Optional list of known entities for matching

    Returns:
        ExtractionResult with entities, relationships, topics, and summary
    """
    if not LLM_ENRICHMENT_ENABLED:
        logger.warning("LLM enrichment disabled (LLM_ENRICHMENT_ENABLED=false)")
        return ExtractionResult()

    if not source_content or not source_content.strip():
        logger.warning("Empty source content, skipping extraction")
        return ExtractionResult()

    # Truncate very long content to stay within context limits
    # Gemini 3 Flash has 1M context, but we cap at 200K chars (~50K tokens) for cost
    max_chars = int(os.getenv("LLM_MAX_CONTENT_CHARS", "200000"))
    if len(source_content) > max_chars:
        logger.info(f"Truncating content from {len(source_content)} to {max_chars} chars")
        source_content = source_content[:max_chars]

    prompt = _build_extraction_prompt(
        source_content, source_title, source_url, existing_entities
    )

    try:
        response_text = await _call_gemini(prompt)
        result = _parse_extraction_response(response_text)
        result.model_used = LLM_GEMINI_MODEL
        return result
    except Exception as e:
        logger.error(f"LLM extraction failed: {e}")
        return ExtractionResult()


async def describe_entities_batch(
    entities: List[dict],
) -> Dict[str, str]:
    """Generate descriptions for a batch of entities using their name, type, and relationships.

    For entities without web source content, uses Gemini's training knowledge
    plus the entity's type and relationships to write grounded descriptions.

    Args:
        entities: List of dicts with keys: name, type, relationships (list of strings)

    Returns:
        Dict mapping entity name → description string
    """
    if not entities:
        return {}

    entity_lines = []
    for e in entities:
        rels = e.get("relationships", [])
        rel_str = "; ".join(rels[:10]) if rels else "none known"
        entity_lines.append(f"- {e['name']} (type: {e['type']}, relationships: {rel_str})")

    prompt = f"""For each entity below, write a concise 1-2 sentence factual description.
These entities are part of a bioregional knowledge commons focused on the Salish Sea region
(Pacific Northwest, British Columbia, Washington State).

Rules:
1. Be factual. If you know specific facts about the entity, use them.
2. If you don't know the entity, write a generic description based on its type and relationships.
3. Do NOT hallucinate specific details you're unsure about.
4. Keep descriptions under 50 words each.

Entities:
{chr(10).join(entity_lines)}

Return JSON object mapping entity name to description string:
{{"Entity Name": "Description...", ...}}
"""

    try:
        response_text = await _call_gemini(prompt)
        descriptions = json.loads(response_text)
        if isinstance(descriptions, dict):
            logger.info(f"Generated {len(descriptions)} descriptions in batch")
            return descriptions
    except Exception as e:
        logger.error(f"Batch description generation failed: {e}")

    return {}


def is_enrichment_available() -> bool:
    """Check if LLM enrichment is configured and available."""
    if not LLM_ENRICHMENT_ENABLED:
        return False
    if LLM_BACKEND == "gemini" and not GEMINI_API_KEY and not VERTEX_PROJECT_ID:
        return False
    return True
