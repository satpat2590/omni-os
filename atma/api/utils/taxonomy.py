"""A small, versioned routing vocabulary. Only tags used by tasks enter the tree."""
import re

REVISION = 1

CATALOG = {
    "physical": {
        "Strength Training": "strength training|lift weights|lifting weights|weight training|weightlifting|deadlift|deadlifts|squat|squats|bench press|push up|pushups",
        "Endurance": "running|jogging|swimming|cycling|cardio|marathon|go for a run|5k",
        "Movement": "gym|walk|walking|hike|hiking|yoga|pilates|workout|stretch|exercise",
        "Nutrition": "meal prep|nutrition|protein|healthy meals|groceries",
        "Health": "dentist|doctor|checkup|physical therapy|sleep|medication",
    },
    "mental": {
        "Computer Science": "computer science|programming|coding|algorithm|algorithms|python|javascript|database|software|leetcode|machine learning",
        "Music": "piano|guitar|violin|singing|music theory",
        "Languages": "spanish|french|japanese|hiragana|language learning",
        "Writing": "write an essay|poem|poetry|journal|writing",
        "Learning": "read|reading|study|course|learn|book",
    },
    "financial": {
        "Budgeting": "budget|budgeting|expenses|monthly spending|cash flow",
        "Bills": "pay rent|pay bills|pay the bill|credit card|electricity bill|mortgage",
        "Investing": "investing|investment|portfolio|index fund|brokerage|retirement",
        "Saving": "savings|emergency fund|save money",
        "Taxes": "taxes|tax return|tax filing",
    },
    "social": {
        "Relationships": "catch up|friend|friends|family|date night|call mom|call dad|visit grandma",
        "Community": "volunteer|volunteering|neighborhood|community event",
        "Networking": "networking|meetup|mentor|mentoring",
        "Communication": "public speaking|active listening|give feedback",
    },
}
GENERIC = {"gym","learn","read","study","book","course"}


def words(value):
    return " ".join(re.findall(r"[^\W_]+", value.casefold()))


def lookup(title, description="", category=None):
    if not title.strip():
        raise ValueError("Enter a task title.")
    text = " " + words(title + " " + (description or "")) + " "
    ranked = []
    for root, labels in CATALOG.items():
        if category and root != category:
            continue
        for name, hints in labels.items():
            terms = {words(name), *hints.split("|")}
            matches = [term for term in terms if " " + term + " " in text]
            if matches:
                score = max((1 if term in GENERIC else 3) + term.count(" ") for term in matches)
                ranked.append((score, root, name))
    ranked.sort(reverse=True)
    if ranked and (len(ranked)==1 or ranked[0][0] > ranked[1][0]):
        _, root, name = ranked[0]
        return root, [name], "catalog"
    return category or "unclassified", [], "pending"
