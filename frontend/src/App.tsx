// Root React tree: router, providers, Job Post page, and toast host.
import { BrowserRouter } from "react-router-dom";
import { JobPostList } from "./pages/JobPostList";
import { Toaster } from "sonner";
import { ConfirmProvider } from "./components/Common/ConfirmProvider";

// Root app: mounts a full-screen overflow-hidden shell, providers, the Job Post page, and toasts.
function App() {
  return (
    <BrowserRouter>
      <div className="h-screen w-screen overflow-hidden bg-slate-50">
        <ConfirmProvider>
          <JobPostList />
        </ConfirmProvider>
        <Toaster richColors position="top-right" closeButton />
      </div>
    </BrowserRouter>
  );
}

export default App;
