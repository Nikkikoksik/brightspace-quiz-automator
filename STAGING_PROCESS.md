# Brightspace Staging Process

## 1. Open Staging Shell
- Hide "How to Use The Blueprint" module

## 2. Copy Components
- Under "Course Admin" select "Import/Export/Copy Components"
- Select "Copy Components from another Org Unit"
- Search for course offering
- Select "Select Components"
- Select all components **except** "grades" and "grade settings"
- Select "Continue" → "Finish"

## 3. Course Outline ✅ (automated)
- Download the .docx file if possible
- Use API app to configure course outline into template
- Paste HTML into course outline template
- Remove copy of course outline from course (keep file in course files)

> **If no syllabus present:** Add comment — *"No syllabus present in course shell - syllabus not applied to syllabus template. Gradebook not set up."*

## 4. Set Up Gradebook
- Use "Setup Wizard" with configurations outlined in video
- Set up grade book according to course outline weightings
- Add and organize gradebook items
  - Add assignment to gradebook
  - Go into gradebook and create a category
  - Edit assignment to move into category

> **If no course syllabus but items exist in gradebook:** Create one category called "Term Work" worth 100% and add all items beneath it. Add/revise comment — *"Grade items present in gradebook so made one category weighted 100% and all items have been placed in this category."*

## 5. Re-Label Staged Course to "Ready"

## 6. Quality Control

## 7. Add Instructor

---

## Wrong Course Imported
1. Reset Course
2. Import Hartwell Sandbox Blueprint course
3. Import the correct course
