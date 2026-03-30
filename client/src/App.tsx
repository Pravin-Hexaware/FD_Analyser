import { RouterProvider } from 'react-router-dom'
import { router } from "./routes";
import { Toaster } from 'react-hot-toast'
import { ExtractionProvider } from './context/ExtractionContext'

export default function App() {
  return (
    <ExtractionProvider>
      <RouterProvider router={router} />
      <Toaster />
    </ExtractionProvider>
  );
}
