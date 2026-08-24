// Modal wrapper that creates a Job Post and reports the new id to the board.
import { JobPostForm } from "../pages/JobPostForm";
import { createJobPost } from "../services/jobService";
import { Modal } from "./Common/Modal";

interface JobPostCreateProps {
  modalTitle: string;
  onClose: () => void;
  onSaved?: (jobId: string) => Promise<void> | void;
}

// Renders the create-job modal and forwards the saved job id to the parent.
export function JobPostCreate({
  modalTitle,
  onClose,
  onSaved,
}: JobPostCreateProps) {
  return (
    <Modal open onClose={onClose}>
      <JobPostForm
        formTitle={modalTitle}
        saveText="Save & Close"
        closeText="Close"
        onSubmit={async (payload) => {
          const created = await createJobPost(payload);
          await onSaved?.(created.id);
          onClose();
        }}
        onClose={onClose}
      />
    </Modal>
  );
}

export { JobPostCreate as jobPostCreate };
