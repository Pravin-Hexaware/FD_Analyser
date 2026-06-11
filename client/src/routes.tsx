import { createBrowserRouter } from "react-router-dom";
import LandingPage from "./app/pages/LandingPage";
import ChatbotPage from "./app/pages/ChatbotPage";
import CompanyPage from "./app/pages/CompanyPage";
import ComparisonPage from "./app/pages/ComparisonPage";
import ReportPage from "./app/pages/ReportPage";
import AdminPage from "./app/pages/AdminPage";
import ErrorPage from "./app/pages/ErrorPage";

const errorElement = <ErrorPage />;

export const router = createBrowserRouter([
  {
    path: "/",
    Component: LandingPage,
    errorElement,
  },
  {
    path: "/chat",
    Component: ChatbotPage,
    errorElement,
  },
  {
    path: "/company/:id",
    Component: CompanyPage,
    errorElement,
  },
  {
    path: "/compare",
    Component: ComparisonPage,
    errorElement,
  },
  {
    path: "/report/:id",
    Component: ReportPage,
    errorElement,
  },
  {
    path: "/admin",
    Component: AdminPage,
    errorElement,
  },
]);
