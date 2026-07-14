"""
Semantic matching service for intelligent package/service mapping.
Uses natural language processing to match package names to available services.
"""

from difflib import SequenceMatcher
from typing import Optional, Tuple


# Common size modifiers to filter out during matching
# NOTE: Color/variant descriptors (gold, silver, bronze, etc.) are NOT included here
# because they help identify the service type (e.g., "gold" identifies "Coating Premium" variants)
SIZE_MODIFIERS = {
    'small', 'medium', 'large', 'xl', 'xs', 's', 'm', 'l', 
    'extra', 'mini', 'big', 'tiny'
}

# Quality/tier descriptors that can be filtered
QUALITY_MODIFIERS = {
    'standard', 'premium', 'basic', 'pro', 'lite', 'deluxe', 'ultimate'
}

# Explicit keyword-to-service mapping for known variant names
KEYWORD_SERVICE_MAP = {
    # Coating Premium variants
    'gold': 'Coating Premium',
    'silver': 'Coating Premium',
    'platinum': 'Coating Premium',
    'graphene': 'Coating Premium',
    'ultimate': 'Coating Premium',
    'ceramic': 'Coating Premium',
    
    # PPF variants - QUAD
    'quad': 'PPF',
    'premiere': 'PPF',
    'luxury': 'PPF',
    'world': 'PPF',  # world class
    'class': 'PPF',
    'colour': 'PPF',  # QUAD Colour
    'color': 'PPF',
    
    # PPF variants - GFIVE
    'gfive': 'PPF',
    'g1': 'PPF',
    'g2': 'PPF',
    'g3': 'PPF',
    
    # Other
    'ppf': 'PPF',
    'paint': 'PPF',
    'protection': 'PPF',
}


def extract_core_keywords(text: str) -> Tuple[set, str]:
    """
    Extract core service keywords from a package name by removing size/variant modifiers.
    
    Returns:
        Tuple of (core_keywords set, original_modifiers_str)
        
    Examples:
        - "medium gold coating" -> ({'coating'}, 'medium gold')
        - "small ppf premium" -> ({'ppf'}, 'small premium')
        - "glass polishing deluxe" -> ({'glass', 'polishing'}, 'deluxe')
    """
    words = text.lower().split()
    core_keywords = set()
    modifiers = []
    
    for word in words:
        if word in SIZE_MODIFIERS:
            modifiers.append(word)
        else:
            core_keywords.add(word)
    
    return core_keywords, ' '.join(modifiers)


def calculate_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity between two strings using SequenceMatcher.
    Returns a value between 0 and 1, where 1 is a perfect match.
    """
    text1_lower = text1.lower().strip()
    text2_lower = text2.lower().strip()
    return SequenceMatcher(None, text1_lower, text2_lower).ratio()


def find_best_matching_service(package_name: str, services: list) -> Optional[Tuple]:
    """
    Find the best matching service for a given package name using semantic similarity.
    Intelligently handles size/variant modifiers.
    
    Args:
        package_name: The package/service name provided by user (e.g., "medium gold", "coating gold")
        services: List of ServiceType objects from database
        
    Returns:
        Tuple of (service_object, similarity_score, variant_info) or None if no good match found
        
    Examples:
        - "small gold" -> matches "Coating Premium" (variant: small gold)
        - "medium gold" -> matches "Coating Premium" (variant: medium gold)
        - "large gold" -> matches "Coating Premium" (variant: large gold)
        - "glasss polish deluxe" -> matches "Glass Polishing" (handles typos, variant: deluxe)
        - "ppf" -> matches "PPF" (no variant)
        - "xyz random" -> None (no good match)
    """
    if not package_name or not services:
        return None
    
    # First, check if any keyword in package matches known service names
    pkg_words = set(package_name.lower().split())
    for word in pkg_words:
        if word in KEYWORD_SERVICE_MAP:
            target_service_name = KEYWORD_SERVICE_MAP[word]
            # Find the service with this name
            for service in services:
                if service.name.lower() == target_service_name.lower() and (not hasattr(service, 'active') or service.active):
                    other_words = ' '.join([w for w in pkg_words if w != word])
                    return (service, 1.0, other_words if other_words else None)
    
    # Extract core keywords and modifiers from package name
    core_keywords, modifiers = extract_core_keywords(package_name)
    
    best_service = None
    best_score = 0.0
    similarity_threshold = 0.5  # Lowered to 50% since we filter modifiers
    
    for service in services:
        # Skip inactive services
        if hasattr(service, 'active') and not service.active:
            continue
        
        # Direct similarity match
        similarity = calculate_similarity(package_name, service.name)
        
        # Also try matching with filtered core keywords
        service_words = set(service.name.lower().split())
        
        # Keyword overlap scoring
        if core_keywords & service_words:  # intersection
            # Higher boost if all core keywords match
            overlap_ratio = len(core_keywords & service_words) / len(core_keywords | service_words)
            similarity = max(similarity, 0.6 + (overlap_ratio * 0.3))
        
        # Update best match if this has better score
        if similarity > best_score:
            best_score = similarity
            best_service = service
    
    # Return only if similarity exceeds threshold
    if best_score >= similarity_threshold:
        variant_info = modifiers.strip() if modifiers.strip() else None
        return (best_service, best_score, variant_info)
    
    return None


def match_package_to_service(package_name: str, services: list) -> Optional:
    """
    Convenience function to get just the service object (not the score).
    """
    result = find_best_matching_service(package_name, services)
    return result[0] if result else None


def get_variant_info(package_name: str, services: list) -> Optional[str]:
    """
    Extract variant information (size, color, quality tier) from package name.
    Returns the variant string to append to notes.
    
    Examples:
        - "small gold coating" -> "small gold"
        - "medium ppf" -> "medium"
        - "large deluxe coating" -> "large deluxe"
    """
    result = find_best_matching_service(package_name, services)
    return result[2] if result else None

