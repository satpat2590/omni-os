"""Atma's reusable paths and the complete activities approved for offline capture."""
import re

REVISION = 3

CATALOG = {
    "physical": {
        ("Strength Training",): ("Lift weights", "Do strength training"),
        ("Strength Training", "Deadlifts"): ("Do deadlifts",),
        ("Strength Training", "Squats"): ("Do squats", "Do three sets of squats at the gym"),
        ("Strength Training", "Bench Press"): ("Practice bench press",),
        ("Strength Training", "Push-ups"): ("Do push-ups",),
        ("Endurance",): ("Go for a run", "Go swimming", "Go cycling"),
        ("Movement",): ("Go to the gym", "Going to the gym"),
        ("Movement", "Walking"): ("Go for a walk",),
        ("Movement", "Hiking"): ("Go hiking",),
        ("Movement", "Yoga"): ("Practice yoga",),
        ("Movement", "Pilates"): ("Do Pilates",),
        ("Movement", "Stretching"): ("Do stretches",),
        ("Nutrition",): ("Plan healthy meals",),
        ("Health",): ("Schedule a checkup",),
    },
    "mental": {
        ("Computer Science",): ("Practice Python algorithms",),
        ("Computer Science", "Algorithms"): ("Study algorithms",),
        ("Computer Science", "Python"): ("Practice Python",),
        ("Computer Science", "JavaScript"): ("Practice JavaScript",),
        ("Computer Science", "Databases"): ("Study databases",),
        ("Computer Science", "Machine Learning"): ("Study machine learning",),
        ("Music",): ("Study music",),
        ("Music", "Piano"): ("Learn piano", "Practice piano"),
        ("Music", "Guitar"): ("Practice guitar",),
        ("Music", "Violin"): ("Practice violin",),
        ("Music", "Singing"): ("Practice singing",),
        ("Music", "Music Theory"): ("Study music theory",),
        ("Languages",): ("Practice a language", "Practice French and Spanish"),
        ("Languages", "French"): ("Practice French",),
        ("Languages", "Spanish"): ("Practice Spanish",),
        ("Languages", "Japanese"): ("Practice Japanese", "Review hiragana and katakana"),
        ("Languages", "Japanese", "Hiragana"): (
            "Practice hiragana", "Practice hiragana alphabet", "Learn the hiragana alphabet", "Practice ひらがな",
        ),
        ("Languages", "Japanese", "Katakana"): ("Practice katakana", "Practice writing katakana"),
        ("Languages", "Japanese", "Kanji"): ("Practice kanji",),
        ("Writing",): ("Write an essay", "Write a poem"),
        ("Learning",): ("Read a book",),
    },
    "financial": {
        ("Budgeting",): ("Review my budget",),
        ("Bills",): ("Pay rent", "Pay bills"),
        ("Investing",): ("Review my investments",),
        ("Saving",): ("Build an emergency fund",),
        ("Taxes",): ("File my taxes",),
    },
    "social": {
        ("Relationships",): ("Catch up with a friend", "Call mom", "Call dad"),
        ("Community",): ("Volunteer in my community",),
        ("Networking",): ("Attend a networking event",),
        ("Communication",): ("Practice public speaking",),
    },
}


def words(value):
    return " ".join(re.findall(r"[^\W_]+", value.casefold()))


def activity_key(value):
    return " ".join(value.casefold().split()).removesuffix(".")


ACTIVITIES = {
    activity_key(activity): (root, path)
    for root, paths in CATALOG.items()
    for path, activities in paths.items()
    for activity in activities
}


def lookup(title, description="", category=None):
    if not title.strip():
        raise ValueError("Enter a task title.")
    match = ACTIVITIES.get(activity_key(title))
    # A description can change even an exact title's intent.
    if match and not (description or "").strip():
        root, path = match
        if not category or root == category:
            return root, list(path), "catalog"
    return category or "unclassified", [], "pending"
