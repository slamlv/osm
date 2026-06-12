from django.urls import path
from .views import StaffMemberAdd, Staff, StaffMemberEdit, StaffMemberDelete, StaffDetails, UserDetails, UserEdit,\
    AddUser, Details, Users, UserDelete, admin, active, StaffMemberTimetable, UserTimetable, ActivityAdd,\
    ActivitiesList, ActivityEdit, ActivityDelete, ProgressionSelectForm, ProgressionEdit, Progression,\
    DeleteArchivedStaff, StaffArchive, StaffToggleEnPoste

urlpatterns = [
    path("staff-add", StaffMemberAdd.as_view(), name="add_staff_member"),
    path("add_user", AddUser.as_view(), name="add_user"),
    path("admin-<int:pk>", admin, name="admin"),
    path("active-<int:pk>", active, name="active"),
    path("staff", Staff.as_view(), name="staff"),
    path("users", Users.as_view(), name="users"),
    path("staff-edit-<int:id>", StaffMemberEdit.as_view(), name="staff-edit"),
    path("staff-delete-<int:id>", StaffMemberDelete.as_view(), name="staff-delete"),
    path("user-<int:id>-delete", UserDelete.as_view(), name="user_delete"),
    path("staff-details-<int:id>", StaffDetails.as_view(), name="staff-details"),
    path("staff-timetable-<int:id>", StaffMemberTimetable.as_view(), name="staff-timetable"),
    path("user-timetable", UserTimetable.as_view(), name="user-timetable"),
    path("user-details", UserDetails.as_view(), name="user-details"),
    path("user-<int:id>-details", Details.as_view(), name="user_details"),
    path("user-edit", UserEdit.as_view(), name="user-edit"),
    path("progression-<int:id>", Progression.as_view(), name="progression"),
    path("progression-edit", ProgressionSelectForm.as_view(), name="progression-edit"),
    path("progression-form", ProgressionEdit.as_view(), name="progression-form"),
    path("activities", ActivitiesList.as_view(), name="activities"),
    path("activity-add", ActivityAdd.as_view(), name="activity-add"),
    path("activity-edit-<int:id>", ActivityEdit.as_view(), name="activity-edit"),
    path("activity-delete-<int:id>", ActivityDelete.as_view(), name="activity-delete"),
    path("staff_archive", StaffArchive.as_view(), name="staff_archive"),
    path("staff_delete_archived", DeleteArchivedStaff.as_view(), name="staff_delete_archived"),
    path("staff_toggle_poste-<int:id>", StaffToggleEnPoste.as_view(), name="staff_toggle_poste")
]
