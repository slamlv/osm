from django.urls import path
from .views import closure_wizard, closure_start, closure_select, refresh_next, closure_verify, closure_consolidate,\
    closure_cleanup, closure_promote, archives_index, archives_search, archive_delete, archives_year, archives_type,\
    archive_delete_group, student_bulletin, archive_download


urlpatterns = [
    path("cloture/", closure_wizard, name="closure_wizard"),
    path("closure_start/", closure_start, name="closure_start"),
    path("closure_select/", closure_select, name="closure_select"),
    path("refresh_next/", refresh_next, name="refresh_next"),
    path("closure_verify/", closure_verify, name="closure_verify"),
    path("closure_consolidate/", closure_consolidate, name="closure_consolidate"),
    path("closure_cleanup/", closure_cleanup, name="closure_cleanup"),
    path("closure_promote/", closure_promote, name="closure_promote"),
    path("archives_index/", archives_index, name="archives_index"),
    path("archives_search/", archives_search, name="archives_search"),
    path("archives_delete-<int:pk>/", archive_delete, name="archive_delete"),
    path("archives_download-<int:pk>/", archive_download, name="archive_download"),
    path("archives_year-<path:year>/", archives_year, name="archives_year"),
    path("archives_type-<path:year>-<str:doc_type>/", archives_type, name="archives_type"),
    path("archives_delete_group-<path:year>-<str:doc_type>/", archive_delete_group, name="archive_delete_group"),
    path("student_bulletin-<int:doc_id>-<int:student_id>/", student_bulletin, name="student_bulletin"),
]
