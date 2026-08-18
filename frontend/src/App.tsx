import { JobPostList } from "./pages/JobPostList";
import { Toaster } from "sonner";
import { ConfirmProvider } from "./components/Common/ConfirmProvider";

// Root app: mounts providers, the Job Post page, and the global toast container.
function App() {
  return (
    <ConfirmProvider>
      <JobPostList />
      <Toaster richColors position="top-right" closeButton />
    </ConfirmProvider>
  );
}

export default App;
