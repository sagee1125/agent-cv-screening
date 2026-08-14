import { JobPostForm } from "../pages/JobPostForm";
import { createJobPost } from "../services/jobService";
import { Modal } from "./Common/Modal";

interface JobPostCreateProps {
  modalTitle: string;
  onClose: () => void;
  onSaved?: () => Promise<void> | void;
}

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
          await createJobPost(payload);
          await onSaved?.();
          onClose();
        }}
        onClose={onClose}
      />
    </Modal>
  );
}

export { JobPostCreate as jobPostCreate };
