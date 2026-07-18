"use client";

import React, { createContext, useContext, useState, useEffect } from "react";

type InstanceContextType = {
  selectedInstance: string;
  setSelectedInstance: (name: string) => void;
};

const InstanceContext = createContext<InstanceContextType | undefined>(undefined);

export function InstanceProvider({ children }: { children: React.ReactNode }) {
  // Default to bulk-sender-main for backward compatibility
  const [selectedInstance, setSelectedInstance] = useState<string>("bulk-sender-main");

  useEffect(() => {
    // Load from local storage on mount
    const saved = localStorage.getItem("selectedInstance");
    if (saved) {
      setSelectedInstance(saved);
    }
  }, []);

  const handleSetSelectedInstance = (name: string) => {
    setSelectedInstance(name);
    localStorage.setItem("selectedInstance", name);
  };

  return (
    <InstanceContext.Provider value={{ selectedInstance, setSelectedInstance: handleSetSelectedInstance }}>
      {children}
    </InstanceContext.Provider>
  );
}

export function useInstance() {
  const context = useContext(InstanceContext);
  if (context === undefined) {
    throw new Error("useInstance must be used within an InstanceProvider");
  }
  return context;
}
