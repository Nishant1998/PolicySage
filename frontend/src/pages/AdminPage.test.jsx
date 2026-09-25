import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AdminPage from "./AdminPage";
import { adminApi } from "../lib/api";

jest.mock("../lib/api", () => ({
  adminApi: { documents: jest.fn(), jobs: jest.fn() },
}));
jest.mock("../components/ps/Header", () => ({ Header: () => null }));
jest.mock("../components/ps/Footer", () => ({ Footer: () => null }));
jest.mock("../components/ui/tabs", () => ({
  Tabs: ({ children }) => <div>{children}</div>,
  TabsContent: ({ children }) => <div>{children}</div>,
  TabsList: ({ children }) => <div>{children}</div>,
  TabsTrigger: ({ children }) => <div>{children}</div>,
}));
jest.mock("../components/admin/AdminTables", () => ({
  DocumentsTable: () => null,
  JobsList: () => null,
}));
jest.mock("../components/admin/UploadDialog", () => ({ UploadDialog: () => null }));

global.IS_REACT_ACT_ENVIRONMENT = true;

test.each([
  "Not authorized. Check the admin username and password.",
  "Too many requests. Please try again shortly.",
])("keeps the sign-in form visible when the server returns %s", async (message) => {
  let rejectRequest;
  adminApi.documents.mockReturnValue(new Promise((_, reject) => { rejectRequest = reject; }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<QueryClientProvider client={client}><AdminPage /></QueryClientProvider>);
  });
  const password = container.querySelector('[data-testid="admin-password-input"]');
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
  await act(async () => {
    setter.call(password, "incorrect");
    password.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  expect(container.querySelector('[data-testid="admin-auth-status"]')).toBeNull();
  expect(adminApi.jobs).not.toHaveBeenCalled();
  await act(async () => {
    rejectRequest(new Error(message));
    await new Promise((resolve) => setTimeout(resolve, 10));
  });
  expect(container.querySelector('[data-testid="admin-auth-status"]')).toBeNull();
  expect(container.querySelector('[data-testid="admin-login-error"]').textContent).toBe(message);
  await act(async () => root.unmount());
  client.clear();
  container.remove();
  jest.clearAllMocks();
});

test("shows the signed-in state after the server accepts the credentials", async () => {
  adminApi.documents.mockResolvedValue([]);
  adminApi.jobs.mockResolvedValue([]);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => root.render(
    <QueryClientProvider client={client}><AdminPage /></QueryClientProvider>
  ));
  const password = container.querySelector('[data-testid="admin-password-input"]');
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
  await act(async () => {
    setter.call(password, "correct");
    password.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 10));
  });
  expect(container.querySelector('[data-testid="admin-auth-status"]').textContent).toContain("Signed in as admin");
  await act(async () => root.unmount());
  client.clear();
  container.remove();
  jest.clearAllMocks();
});

test("does not poll while idle and refreshes both lists when requested", async () => {
  adminApi.documents.mockResolvedValue([]);
  adminApi.jobs.mockResolvedValue([]);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 60000 } } });
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => root.render(
    <QueryClientProvider client={client}><AdminPage /></QueryClientProvider>
  ));
  const password = container.querySelector('[data-testid="admin-password-input"]');
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
  await act(async () => {
    setter.call(password, "correct");
    password.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
  expect(adminApi.documents).toHaveBeenCalledTimes(1);
  expect(adminApi.jobs).toHaveBeenCalledTimes(1);
  jest.useFakeTimers();
  await act(async () => { jest.advanceTimersByTime(31000); });
  expect(adminApi.documents).toHaveBeenCalledTimes(1);
  expect(adminApi.jobs).toHaveBeenCalledTimes(1);
  await act(async () => {
    container.querySelector('[data-testid="admin-refresh-button"]').click();
  });
  expect(adminApi.documents).toHaveBeenCalledTimes(2);
  expect(adminApi.jobs).toHaveBeenCalledTimes(2);
  await act(async () => root.unmount());
  client.clear();
  container.remove();
  jest.useRealTimers();
  jest.clearAllMocks();
});
