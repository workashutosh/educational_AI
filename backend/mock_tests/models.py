from __future__ import annotations

from datetime import timedelta

from django.db import models
from django.db.models import Sum
from django.utils import timezone

from ingestion.models import School, SchoolMembership, SubjectBucket


class MockTest(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PUBLISHED, "Published"),
        (STATUS_CLOSED, "Closed"),
    ]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="mock_tests")
    bucket = models.ForeignKey(
        SubjectBucket, on_delete=models.CASCADE, related_name="mock_tests"
    )
    created_by = models.ForeignKey(
        SchoolMembership,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_mock_tests",
    )
    title = models.CharField(max_length=255)
    topic_prompt = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    question_count = models.PositiveIntegerField(default=0)
    duration_minutes = models.PositiveIntegerField(default=60)
    count_mcq = models.PositiveIntegerField(default=0)
    count_multi = models.PositiveIntegerField(default=0)
    count_brief = models.PositiveIntegerField(default=0)
    marks_mcq = models.PositiveIntegerField(default=1)
    marks_multi = models.PositiveIntegerField(default=2)
    marks_brief = models.PositiveIntegerField(default=5)
    # immediate = students see score/review right after submit
    # after_review = teacher reviews first, then releases results to student
    RESULTS_IMMEDIATE = "immediate"
    RESULTS_AFTER_REVIEW = "after_review"
    RESULTS_MODE_CHOICES = [
        (RESULTS_IMMEDIATE, "Show results immediately"),
        (RESULTS_AFTER_REVIEW, "Teacher reviews first, then releases"),
    ]
    results_mode = models.CharField(
        max_length=20,
        choices=RESULTS_MODE_CHOICES,
        default=RESULTS_AFTER_REVIEW,
    )
    SOURCE_NOTES = "notes"
    SOURCE_QUESTION_PAPERS = "question_papers"
    SOURCE_BOTH = "both"
    SOURCE_MODE_CHOICES = [
        (SOURCE_NOTES, "Teaching notes"),
        (SOURCE_QUESTION_PAPERS, "Previous year papers"),
        (SOURCE_BOTH, "Notes + previous year papers"),
    ]
    source_mode = models.CharField(
        max_length=32,
        choices=SOURCE_MODE_CHOICES,
        default=SOURCE_NOTES,
        help_text="Which indexed bucket documents to use when generating questions.",
    )
    # When source_mode includes question papers, limit retrieval to these document IDs.
    # Empty list = use all indexed papers in the bucket.
    reference_document_ids = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.status})"

    @property
    def blueprint_max_score(self) -> int:
        return (
            self.count_mcq * self.marks_mcq
            + self.count_multi * self.marks_multi
            + self.count_brief * self.marks_brief
        )

    def computed_max_score(self) -> int:
        total = self.questions.aggregate(s=Sum("marks"))["s"]
        return int(total or 0)

    def mark_published(self):
        self.status = self.STATUS_PUBLISHED
        self.published_at = timezone.now()
        self.save(update_fields=["status", "published_at"])

    def mark_closed(self):
        self.status = self.STATUS_CLOSED
        self.closed_at = timezone.now()
        self.save(update_fields=["status", "closed_at"])


class MockQuestion(models.Model):
    TYPE_MCQ = "mcq"
    TYPE_MULTI = "multi"
    TYPE_BRIEF = "brief"
    TYPE_CHOICES = [
        (TYPE_MCQ, "Single MCQ"),
        (TYPE_MULTI, "Multi-select"),
        (TYPE_BRIEF, "Brief"),
    ]

    test = models.ForeignKey(MockTest, on_delete=models.CASCADE, related_name="questions")
    order = models.PositiveIntegerField(default=0)
    qtype = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TYPE_MCQ)
    prompt = models.TextField()
    options = models.JSONField(default=list, blank=True)
    correct_indices = models.JSONField(default=list, blank=True)
    model_answer = models.TextField(blank=True, default="")
    marks = models.PositiveIntegerField(default=1)
    # Topic tag (drives weak-topic analytics) and the bank row it came from.
    topic = models.ForeignKey(
        "question_bank.Topic",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mock_questions",
    )
    bank_item = models.ForeignKey(
        "question_bank.QuestionItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mock_questions",
    )

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"Q{self.order} [{self.qtype}]: {self.prompt[:40]}"


class MockAssignment(models.Model):
    test = models.ForeignKey(MockTest, on_delete=models.CASCADE, related_name="assignments")
    student = models.ForeignKey(
        SchoolMembership,
        on_delete=models.CASCADE,
        related_name="mock_assignments",
        limit_choices_to={"role": SchoolMembership.ROLE_STUDENT},
    )
    assigned_by = models.ForeignKey(
        SchoolMembership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("test", "student")
        ordering = ["-assigned_at"]

    def __str__(self):
        return f"{self.student} → {self.test}"


class MockAttempt(models.Model):
    GRADING_IN_PROGRESS = "in_progress"
    GRADING_PARTIAL = "partially_graded"
    GRADING_FINAL = "final"
    GRADING_CHOICES = [
        (GRADING_IN_PROGRESS, "In progress"),
        (GRADING_PARTIAL, "Partially graded"),
        (GRADING_FINAL, "Final"),
    ]

    test = models.ForeignKey(MockTest, on_delete=models.CASCADE, related_name="attempts")
    student = models.ForeignKey(
        SchoolMembership,
        on_delete=models.CASCADE,
        related_name="mock_attempts",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    auto_submitted = models.BooleanField(default=False)
    answers = models.JSONField(default=dict, blank=True)
    score = models.FloatField(default=0.0)
    max_score = models.PositiveIntegerField(default=0)
    objective_score = models.FloatField(default=0.0)
    brief_pending_count = models.PositiveIntegerField(default=0)
    percent = models.FloatField(default=0.0)
    grading_status = models.CharField(
        max_length=32, choices=GRADING_CHOICES, default=GRADING_IN_PROGRESS
    )
    results_released_at = models.DateTimeField(null=True, blank=True)
    results_released_by = models.ForeignKey(
        SchoolMembership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        unique_together = ("test", "student")
        ordering = ["-submitted_at", "-started_at"]

    def __str__(self):
        return f"{self.student} attempt on {self.test}"

    @property
    def is_submitted(self) -> bool:
        return self.submitted_at is not None

    @property
    def results_released(self) -> bool:
        return self.results_released_at is not None

    def student_can_see_results(self) -> bool:
        if not self.is_submitted:
            return False
        if self.test.results_mode == MockTest.RESULTS_IMMEDIATE:
            return True
        return self.results_released

    def release_results(self, by: SchoolMembership | None = None) -> None:
        if not self.is_submitted:
            return
        self.results_released_at = timezone.now()
        self.results_released_by = by
        self.save(update_fields=["results_released_at", "results_released_by"])

    def set_ends_at_from_test(self) -> None:
        minutes = max(1, int(self.test.duration_minutes or 60))
        self.ends_at = self.started_at + timedelta(minutes=minutes)
        self.save(update_fields=["ends_at"])

    def recompute_scores(self) -> None:
        """Recompute official score from objective + confirmed brief grades."""
        questions = list(self.test.questions.all())
        max_score = sum(int(q.marks) for q in questions)
        objective = 0.0
        brief_pending = 0
        brief_confirmed = 0.0

        grades = {
            g.question_id: g
            for g in self.answer_grades.select_related("question").all()
        }

        for q in questions:
            raw = self.answers.get(str(q.id))
            if raw is None:
                raw = self.answers.get(q.id)

            if q.qtype == MockQuestion.TYPE_MCQ:
                try:
                    selected = int(raw) if raw is not None else None
                except (TypeError, ValueError):
                    selected = None
                correct = q.correct_indices or []
                if selected is not None and correct and selected == int(correct[0]):
                    objective += float(q.marks)
            elif q.qtype == MockQuestion.TYPE_MULTI:
                selected_set = _as_index_set(raw)
                correct_set = set(int(i) for i in (q.correct_indices or []))
                if selected_set is not None and selected_set == correct_set and correct_set:
                    objective += float(q.marks)
            else:  # brief
                grade = grades.get(q.id)
                if grade is None or grade.teacher_score is None:
                    brief_pending += 1
                else:
                    brief_confirmed += float(grade.teacher_score)

        official = objective + brief_confirmed
        self.objective_score = objective
        self.brief_pending_count = brief_pending
        self.score = official
        self.max_score = max_score
        self.percent = round((official / max_score) * 100, 1) if max_score else 0.0
        if self.is_submitted:
            self.grading_status = (
                self.GRADING_FINAL if brief_pending == 0 else self.GRADING_PARTIAL
            )
        self.save(
            update_fields=[
                "objective_score",
                "brief_pending_count",
                "score",
                "max_score",
                "percent",
                "grading_status",
            ]
        )


def _as_index_set(raw) -> set[int] | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        try:
            return {int(x) for x in raw}
        except (TypeError, ValueError):
            return None
    if isinstance(raw, (int, float)):
        return {int(raw)}
    return None


class MockAnswerGrade(models.Model):
    attempt = models.ForeignKey(
        MockAttempt, on_delete=models.CASCADE, related_name="answer_grades"
    )
    question = models.ForeignKey(
        MockQuestion, on_delete=models.CASCADE, related_name="answer_grades"
    )
    student_answer = models.TextField(blank=True, default="")
    ai_score = models.FloatField(null=True, blank=True)
    ai_feedback = models.TextField(blank=True, default="")
    teacher_score = models.FloatField(null=True, blank=True)
    teacher_feedback = models.TextField(blank=True, default="")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        SchoolMembership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        unique_together = ("attempt", "question")

    def __str__(self):
        return f"Grade Q{self.question_id} attempt {self.attempt_id}"
