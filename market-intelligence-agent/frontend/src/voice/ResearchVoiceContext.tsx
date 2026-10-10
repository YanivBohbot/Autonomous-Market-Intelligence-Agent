import {
  createContext,
  useContext,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import { useResearchVoice } from "./useResearchVoice";

export type ResearchVoiceContextValue = ReturnType<typeof useResearchVoice> & {
  enabled: boolean;
  typedApprovalPending: boolean;
  setTypedApprovalPending: Dispatch<SetStateAction<boolean>>;
};

export const ResearchVoiceContext =
  createContext<ResearchVoiceContextValue | null>(null);

export function ResearchVoiceProvider({
  threadId,
  enabled,
  children,
}: {
  threadId: string;
  enabled: boolean;
  children: ReactNode;
}) {
  const voice = useResearchVoice(threadId, enabled);
  const [typedApprovalPending, setTypedApprovalPending] = useState(false);

  return (
    <ResearchVoiceContext.Provider
      value={{
        ...voice,
        enabled,
        typedApprovalPending,
        setTypedApprovalPending,
      }}
    >
      {children}
    </ResearchVoiceContext.Provider>
  );
}

export function useResearchVoiceContext() {
  return useContext(ResearchVoiceContext);
}
