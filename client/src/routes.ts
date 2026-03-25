import { createBrowserRouter } from "react-router-dom";
import LandingPage from "./app/pages/LandingPage";
import ChatbotPage from "./app/pages/ChatbotPage";
import CompanyPage from "./app/pages/CompanyPage";
import ComparisonPage from "./app/pages/ComparisonPage";
import ReportPage from "./app/pages/ReportPage";
import AdminPage from "./app/pages/AdminPage";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: LandingPage,
  },
  {
    path: "/chat",
    Component: ChatbotPage,
  },
  {
    path: "/company/:id",
    Component: CompanyPage,
  },
  {
    path: "/compare",
    Component: ComparisonPage,
  },
  {
    path: "/report/:id",
    Component: ReportPage,
  },
  {
    path: "/admin",
    Component: AdminPage,
  },
]);
