from django.urls import path
from student.views import StudentAdd, ParentAdd, ParentEdit, ParentDelete, StudentEdit, StudentDelete,\
    Students, StudentDetails, ParentDetails, Parents, discipline, Discipline, StudentsImport, students_export,\
    StudentsIdCards, EndYearAssignment, EndYearAssignmentForm, StudentJourney, StudentsTrash, StudentsWithoutClass,\
    StudentToggleActive, DeleteDeactivatedStudents, DeleteStudentsWithoutClass, AssignClassToWithoutClass

urlpatterns = [
    path("students", Students.as_view(), name="students"),
    path("student-add", StudentAdd.as_view(), name="student-add"),
    path("student-edit-<int:id>", StudentEdit.as_view(), name="student-edit"),
    path("student-details-<int:id>", StudentDetails.as_view(), name="student-details"),
    path("student-delete-<int:id>", StudentDelete.as_view(), name="student-delete"),
    path("students_import", StudentsImport.as_view(), name="students_import"),
    path("students_export-<int:cls_id>", students_export, name="students_export"),
    path("students_id_cards", StudentsIdCards.as_view(), name="students_id_cards"),
    path("parents", Parents.as_view(), name="parents"),
    path("parent-add", ParentAdd.as_view(), name="parent-add"),
    path("parent-edit-<int:id>", ParentEdit.as_view(), name="parent-edit"),
    path("parent-details-<int:id>", ParentDetails.as_view(), name="parent-details"),
    path("parent-delete-<int:id>", ParentDelete.as_view(), name="parent-delete"),
    path("discipline", discipline, name="discipline"),
    path("discipline-edit-<int:id>-<int:trim>", Discipline.as_view(), name="discipline-edit"),
    path("end_year_assignment", EndYearAssignment.as_view(), name="end_year_assignment"),
    path("end_year_assignment_form", EndYearAssignmentForm.as_view(), name="end_year_assignment_form"),
    path("student_journey-<int:id>", StudentJourney.as_view(), name="student_journey"),
    path("students_corbeille", StudentsTrash.as_view(), name="students_trash"),
    path("students_without_class", StudentsWithoutClass.as_view(), name="students_without_class"),
    path("student_toggle_active-<int:id>", StudentToggleActive.as_view(), name="student_toggle_active"),
    path("students_delete_deactivated", DeleteDeactivatedStudents.as_view(), name="students_delete_deactivated"),
    path("students_delete_without_class", DeleteStudentsWithoutClass.as_view(), name="students_delete_without_class"),
    path("class_bulk_assignment", AssignClassToWithoutClass.as_view(), name="class_bulk_assignment")
]
