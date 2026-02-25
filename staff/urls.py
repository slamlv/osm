from django.contrib.auth.decorators import login_required
from django.urls import path
from .views import StaffMemberAdd, Staff, StaffMemberEdit, StaffMemberDelete, StaffDetails, UserDetails, UserEdit,\
    AddUser, Details, Users, UserDelete, admin, active, StaffMemberTimetable, UserTimetable, ActivityAdd,\
    ActivitiesList, ActivityEdit, ActivityDelete, ProgressionSelectForm, ProgressionEdit, Progression

urlpatterns = [
    path("staff-add", login_required(StaffMemberAdd.as_view(), login_url="signin"), name="add_staff_member"),
    path("add_user", login_required(AddUser.as_view(), login_url="signin"), name="add_user"),
    path("admin-<int:pk>", login_required(admin, login_url="signin"), name="admin"),
    path("active-<int:pk>", login_required(active, login_url="signin"), name="active"),
    path("staff", login_required(Staff.as_view(), login_url="signin"), name="staff"),
    path("users", login_required(Users.as_view(), login_url="signin"), name="users"),
    path("staff-edit-<int:id>", login_required(StaffMemberEdit.as_view(), login_url="signin"), name="staff-edit"),
    path("staff-delete-<int:id>", login_required(StaffMemberDelete.as_view(), login_url="signin"), name="staff-delete"),
    path("user-<int:id>-delete", login_required(UserDelete.as_view(), login_url="signin"), name="user_delete"),
    path("staff-details-<int:id>", login_required(StaffDetails.as_view(), login_url="signin"), name="staff-details"),
    path("staff-timetable-<int:id>", login_required(StaffMemberTimetable.as_view(), login_url="signin"),
         name="staff-timetable"),
    path("user-timetable", login_required(UserTimetable.as_view(), login_url="signin"), name="user-timetable"),
    path("user-details", login_required(UserDetails.as_view(), login_url="signin"), name="user-details"),
    path("user-<int:id>-details", login_required(Details.as_view(), login_url="signin"), name="user_details"),
    path("user-edit", login_required(UserEdit.as_view(), login_url="signin"), name="user-edit"),
    path("progression-<int:id>", login_required(Progression.as_view(), login_url="signin"), name="progression"),
    path("progression-edit", login_required(ProgressionSelectForm.as_view(), login_url="signin"), name="progression-edit"),
    path("progression-form", login_required(ProgressionEdit.as_view(), login_url="signin"), name="progression-form"),
    path("activities", login_required(ActivitiesList.as_view(), login_url="signin"), name="activities"),
    path("activity-add", login_required(ActivityAdd.as_view(), login_url="signin"), name="activity-add"),
    path("activity-edit-<int:id>", login_required(ActivityEdit.as_view(), login_url="signin"), name="activity-edit"),
    path("activity-delete-<int:id>", login_required(ActivityDelete.as_view(), login_url="signin"), name="activity-delete"),
]
