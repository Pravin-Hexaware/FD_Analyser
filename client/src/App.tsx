import './App.css'
import { RouterProvider } from 'react-router-dom'
import { router } from "./routes";
import { Toaster } from 'react-hot-toast'

import { ExtractionProvider } from './context/ExtractionContext'
import { SidebarProvider } from './context/SidebarContext'

export default function App() {
  return (
    <>
    <SidebarProvider>
      <ExtractionProvider>
        <RouterProvider router={router} />
        <Toaster />
      </ExtractionProvider>
    </SidebarProvider>
    </>
  );
}
