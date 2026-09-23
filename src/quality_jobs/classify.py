from __future__ import annotations

import re

from .models import Job


AI_TERMS = {
    "ai trainer",
    "ai training",
    "ai evaluator",
    "model evaluator",
    "llm evaluator",
    "prompt evaluator",
    "response evaluator",
    "data annotation",
    "data annotator",
    "data labeling",
    "rlhf",
    "machine learning",
    "artificial intelligence",
    "search quality rater",
    "ads quality rater",
    "speech collection",
    "voice recording",
    "media quality evaluator",
    "speakers wanted",
}

EASY_ENTRY_TERMS = {
    "entry level",
    "entry-level",
    "no experience required",
    "no prior experience",
    "junior",
    "intern",
    "internship",
    "apprentice",
    "trainee",
    "graduate",
    "technical support",
    "customer support",
    "help desk",
    "helpdesk",
    "manual qa",
    "qa tester",
    "software tester",
    "data annotator",
    "data annotation",
    "ai trainer",
    "ai evaluator",
    "model evaluator",
    "llm evaluator",
    "response evaluator",
    "search quality rater",
    "ads quality rater",
    "speech collection",
    "voice recording",
    "media quality evaluator",
    "speakers wanted",
    "transcription",
    "content moderator",
    "community moderator",
    "no-code",
    "nocode",
}

SENIOR_TERMS = {"senior", "staff", "principal", "lead", "manager", "director", "head of"}

WORLDWIDE_TERMS = {
    "worldwide",
    "world wide",
    "anywhere",
    "global remote",
    "remote globally",
    "any country",
}
AFRICA_TERMS = {
    "africa",
    "nigeria",
    "emea",
    "ghana",
    "kenya",
    "south africa",
    "egypt",
    "morocco",
}
LATAM_TERMS = {
    "latam", "latin america", "south america", "central america", "costa rica",
    "chile", "peru", "mexico", "brazil", "argentina", "colombia",
}
EUROPE_TERMS = {
    "europe", "european union", "emea", "uk/eu", "eu only", "denmark",
    "croatia", "czech", "georgia", "germany", "france", "italy", "spain",
    "portugal", "united kingdom",
}
US_TERMS = {
    "united states", "us only", "usa only", "u.s. only", "north america", "en-us",
    "vi-us",
}
ASIA_TERMS = {"asia", "apac", "india", "indonesia", "japan", "south korea", "philippines"}
MIDDLE_EAST_TERMS = {
    "middle east", "mena", "uae", "united arab emirates", "saudi arabia", "dubai",
    "ar-ae", "ar-sa", "ar-qa", "qatar",
}


def _contains(text: str, terms: set[str]) -> bool:
    return any(term in text for term in terms)


def classify(job: Job) -> Job:
    text = " ".join(
        [job.title, job.description, job.location, job.employment_type]
    ).lower()

    if _contains(text, AI_TERMS):
        job.category = "ai"
        if _contains(text, {"annotation", "labeling", "evaluator", "rater", "transcription"}):
            job.opportunity_type = "ai_gig"
    elif _contains(text, {"web3", "blockchain", "crypto", "solidity", "defi"}):
        job.category = "web3"
    else:
        job.category = "tech"

    if _contains(text, SENIOR_TERMS):
        job.experience_level = "senior"
    elif _contains(text, EASY_ENTRY_TERMS):
        years = [int(value) for value in re.findall(r"\b(\d{1,2})\+? years?\b", text)]
        job.experience_level = "entry" if not years or min(years) <= 2 else "mid"
    elif re.search(r"\b(?:2|3)[-– ](?:4|5) years?\b", text) or "mid-level" in text:
        job.experience_level = "mid"
    else:
        job.experience_level = "not_specified"

    if _contains(text, WORLDWIDE_TERMS):
        job.remote_scope = "worldwide"
    elif _contains(text, AFRICA_TERMS):
        job.remote_scope = "africa"
        job.africa_eligible = True
    elif _contains(text, LATAM_TERMS):
        job.remote_scope = "latam"
    elif "emea" in text:
        job.remote_scope = "emea"
    elif _contains(text, EUROPE_TERMS):
        job.remote_scope = "europe"
    elif _contains(text, US_TERMS):
        job.remote_scope = "us_canada"
    elif _contains(text, ASIA_TERMS):
        job.remote_scope = "asia"
    elif _contains(text, MIDDLE_EAST_TERMS):
        job.remote_scope = "middle_east"
    else:
        job.remote_scope = "unknown"

    if job.remote_scope == "worldwide":
        job.africa_eligible = True

    # Mercor's published policy says unspecified listings default to US/CA/UK/EU.
    if job.source.lower() == "mercor" and job.remote_scope == "unknown":
        job.remote_scope = "us_ca_uk_eu"
        job.africa_eligible = False

    keywords = [job.title, job.category, job.experience_level, "remote job"]
    if job.remote_scope == "worldwide":
        keywords.append("worldwide")
    if job.africa_eligible:
        keywords.append("Africa friendly")
    job.search_keywords = ", ".join(dict.fromkeys(x for x in keywords if x))
    return job
