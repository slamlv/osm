from django.urls import path
from .views import Marks, MarksEdit, classrooms_set, SetPeriods, MarksCheck, check, Bulletin, TrimesterMarks,\
    TrimesterMarksEdit, competences, LevelMarks, LevelMarksEdit, levels_set, TLevelMarksEdit,\
    TLevelMarks, MarksReport, reload_period, MarksCopy, ReloadCopyForm, ReloadCopyFormEvals, ExamReport,\
    download_and_delete, TableauHonneur

urlpatterns = [
    path("marks", Marks.as_view(), name="marks"),
    path("level-marks", LevelMarks.as_view(), name="level-marks"),
    path("tlevel-marks", TLevelMarks.as_view(), name="tlevel-marks"),
    path("trimester-marks", TrimesterMarks.as_view(), name="trimester-marks"),
    path("marks_check", MarksCheck.as_view(), name="marks_check"),
    path("check", check, name="check"),
    path("classrooms_set", classrooms_set, name="classrooms_set"),
    path("levels_set", levels_set, name="level_set"),
    path("reload_period", reload_period, name="reload_period"),
    path("set_periods", SetPeriods.as_view(), name="set_periods"),
    path("set_competences-<int:evl>", competences, name="set_competences"),
    path("marks-edit", MarksEdit.as_view(), name="marks-edit"),
    path("level-marks-edit", LevelMarksEdit.as_view(), name="level-marks-edit"),
    path("tlevel-marks-edit", TLevelMarksEdit.as_view(), name="tlevel-marks-edit"),
    path("trimester-marks-edit", TrimesterMarksEdit.as_view(), name="trimester-marks-edit"),
    path("bulletin", Bulletin.as_view(), name="bulletin"),
    path("download_and_delete-<str:filename>", download_and_delete, name="download_and_delete"),
    path("marks_report", MarksReport.as_view(), name="marks_report"),
    path("exam_report", ExamReport.as_view(), name="exam_report"),
    path("tableau_honneur", TableauHonneur.as_view(), name="tableau_honneur"),
    path("marks-copy", MarksCopy.as_view(), name="marks-copy"),
    path("reload-copy-form", ReloadCopyForm.as_view(), name="reload-copy-form"),
    path("reload-copy-form-evals", ReloadCopyFormEvals.as_view(), name="reload-copy-form-evals")
]
