from django.urls import path
from .views import ClassroomAdd, ClassRooms, ClassroomDelete, ClassRoomStudents, SubjectDelete, ClassRoomTeachers,\
    classroom_form_reload, ClassroomEdit, Subjects, SubjectAdd, SubjectEdit, StatsCheck, MarksSheet,\
    classroom_list, ClassMatieres, MatiereAdd, reload, RemoveMatiere, TimeTable, TimeTableForm, SetProgrammation,\
    reload_teachers, ClassRoomProgression, ClassRoomProgressionSelectForm, TitulaireAssignment,\
    ClassPhotosPage, StudentPhotoUpload, ClassroomsLists, Stats

urlpatterns = [
    path("classroom-add", ClassroomAdd.as_view(), name="classroom-add"),
    path("classroom-edit-<int:id>", ClassroomEdit.as_view(), name="classroom-edit"),
    path("form-reload-<int:key>", classroom_form_reload, name="form-reload"),
    path("marks-sheet", MarksSheet.as_view(), name="marks-sheet"),
    path("subjects", Subjects.as_view(), name="subjects"),
    path("reload", reload, name="reload"),
    path("subject-add", SubjectAdd.as_view(), name="subject-add"),
    path("matiere-<int:id>-add", MatiereAdd.as_view(), name="matiere-add"),
    path("matiere-<int:cid>-<int:id>-remove", RemoveMatiere.as_view(), name="matiere-remove"),
    path("subject-<int:id>-edit", SubjectEdit.as_view(), name="subject-edit"),
    path("subject-<int:id>-delete", SubjectDelete.as_view(), name="subject-delete"),
    path("classroom-progression-select", ClassRoomProgressionSelectForm.as_view(), name="classroom-progression-select"),
    path("classroom-progression", ClassRoomProgression.as_view(), name="classroom-progression"),
    path("classrooms", ClassRooms.as_view(), name="classrooms"),
    path("classroom-<int:id>-students", ClassRoomStudents.as_view(), name="classroom-students"),
    path("classroom-<int:id>-delete", ClassroomDelete.as_view(), name="classroom-delete"),
    path("classroom-<int:id>-teachers", ClassRoomTeachers.as_view(), name="classroom-teachers"),
    path("class-<int:id>-subjects", ClassMatieres.as_view(), name="class-subjects"),
    path("classroom-<int:id>-list", classroom_list, name="classroom-list"),
    path("classrooms_lists", ClassroomsLists.as_view(), name="classrooms_lists"),
    path("classroom-<int:id>-list", classroom_list, name="classroom-list"),
    path("classroom_time_table", TimeTableForm.as_view(), name="classroom_time_table"),
    path("time_table", TimeTable.as_view(), name="time_table"),
    path("set_programmation", SetProgrammation.as_view(), name="set_programmation"),
    path("reload_teachers", reload_teachers, name="reload_teachers"),
    path("stats", Stats.as_view(), name="stats"),
    path("stats-check", StatsCheck.as_view(), name="stats-check"),
    path("titulaire_assignment", TitulaireAssignment.as_view(), name="titulaire_assignment"),
    path("class_photos_update-<int:id>", ClassPhotosPage.as_view(), name="class_photos_update"),
    path("class-<int:id>-student_photo-<int:student_id>", StudentPhotoUpload.as_view(), name="student_photo_upload")
]
