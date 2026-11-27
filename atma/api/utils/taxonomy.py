"""A small, versioned routing vocabulary. Only tags used by tasks enter the tree."""
import re

REVISION = 2

CATALOG = {
    "physical": {
        ("Strength Training",): "strength training|lift weights|lifting weights|weight training|weightlifting",
        ("Strength Training", "Deadlifts"): "deadlift",
        ("Strength Training", "Squats"): "squat",
        ("Strength Training", "Bench Press"): "",
        ("Strength Training", "Push-ups"): "push up|push ups|pushup|pushups",
        ("Endurance",): "running|jogging|swimming|cycling|cardio|marathon|go for a run|5k",
        ("Movement",): "gym|workout|exercise",
        ("Movement", "Walking"): "walk",
        ("Movement", "Hiking"): "hike",
        ("Movement", "Yoga"): "",
        ("Movement", "Pilates"): "",
        ("Movement", "Stretching"): "stretch",
        ("Nutrition",): "meal prep|nutrition|protein|healthy meals|groceries",
        ("Health",): "dentist|doctor|checkup|physical therapy|sleep|medication",
    },
    "mental": {
        ("Computer Science",): "computer science|programming|coding|software",
        ("Computer Science", "Algorithms"): "algorithm|leetcode",
        ("Computer Science", "Python"): "",
        ("Computer Science", "JavaScript"): "",
        ("Computer Science", "Databases"): "database",
        ("Computer Science", "Machine Learning"): "",
        ("Music",): "",
        ("Music", "Piano"): "",
        ("Music", "Guitar"): "",
        ("Music", "Violin"): "",
        ("Music", "Singing"): "",
        ("Music", "Music Theory"): "",
        ("Languages",): "language learning|learn a language|practice a language",
        ("Languages", "French"): "",
        ("Languages", "Spanish"): "",
        ("Languages", "Japanese"): "",
        ("Languages", "Japanese", "Hiragana"): "ひらがな",
        ("Languages", "Japanese", "Katakana"): "カタカナ",
        ("Languages", "Japanese", "Kanji"): "漢字",
        ("Writing",): "write an essay|poem|poetry|journal|writing",
        ("Learning",): "read|reading|study|course|learn|book",
    },
    "financial": {
        ("Budgeting",): "budget|budgeting|expenses|monthly spending|cash flow",
        ("Bills",): "pay rent|pay bills|pay the bill|credit card|electricity bill|mortgage",
        ("Investing",): "investing|investment|portfolio|index fund|brokerage|retirement",
        ("Saving",): "savings|emergency fund|save money",
        ("Taxes",): "taxes|tax return|tax filing",
    },
    "social": {
        ("Relationships",): "catch up|friend|friends|family|date night|call mom|call dad|visit grandma",
        ("Community",): "volunteer|volunteering|neighborhood|community event",
        ("Networking",): "networking|meetup|mentor|mentoring",
        ("Communication",): "public speaking|active listening|give feedback",
    },
}
GENERIC = {"gym","learn","read","study","book","course","writing","learning"}


def words(value):
    return " ".join(re.findall(r"[^\W_]+", value.casefold()))


def lookup(title, description="", category=None):
    if not title.strip():
        raise ValueError("Enter a task title.")
    text = " " + words(title + " " + (description or "")) + " "
    # Each matching term supports its full branch. Choose among siblings only.
    scores = {}
    for root, paths in CATALOG.items():
        if category and root != category:
            continue
        for path, hints in paths.items():
            terms = [words(path[-1]), *filter(None, hints.split("|"))]
            matches = [term for term in terms if " " + term + " " in text]
            if matches:
                score = max((1 if term in GENERIC else 3) + term.count(" ") for term in matches)
                branch = (root, *path)
                for depth in range(2, len(branch) + 1):
                    prefix = branch[:depth]
                    scores[prefix] = max(score, scores.get(prefix, 0))

    # Keep the existing pending behavior for ambiguous base tags. Below a
    # known base, a sibling tie resolves to the most specific shared parent.
    def winner(candidates):
        best = max((scores[path] for path in candidates), default=0)
        leaders = [path for path in candidates if scores[path] == best]
        return leaders[0] if len(leaders) == 1 else None

    branch = winner([path for path in scores if len(path) == 2])
    if branch is None:
        return category or "unclassified", [], "pending"
    while child := winner([path for path in scores if path[:-1] == branch]):
        branch = child
    return branch[0], list(branch[1:]), "catalog"
