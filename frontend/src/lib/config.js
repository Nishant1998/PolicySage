export const API_BASE = "";

export const ENDPOINTS = {
  chat: "/api/chat",
  documents: "/api/admin/kb/documents",
  jobs: "/api/admin/kb/jobs",
  revisions: (docId) => `/api/admin/kb/documents/${docId}/revisions`,
  approve: (revisionId) => `/api/admin/kb/revisions/${revisionId}/approve`,
  retry: (jobId) => `/api/admin/kb/jobs/${jobId}/retry`,
  withdraw: (docId) => `/api/admin/kb/documents/${docId}`,
  preview: (revisionId) => `/api/admin/kb/revisions/${revisionId}/preview`,
};

export const LINKS = {
  github: "",
  portfolio: "",
};
