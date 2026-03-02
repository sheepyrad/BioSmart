import { useState, useCallback } from 'react';
import { useMutation, useQuery } from 'convex/react';
import { api } from '../../convex/_generated/api';
import { useConvexAvailable } from './useConvex';
import type { Id } from '../../convex/_generated/dataModel';

export type FieldType = 'protein_pdb' | 'boltz_yaml' | 'msa' | 'other';
export type FileType = 'pdb' | 'yaml' | 'msa' | 'db' | 'other';

export interface UploadedFile {
  _id: Id<'files'>;
  name: string;
  type: FileType;
  fieldType: FieldType;
  storageId: Id<'_storage'>;
  size: number;
  createdAt: number;
  url: string | null; // Download URL from Convex storage
}

interface UseUploadedFilesResult {
  // List of files for a specific field type (includes URLs)
  files: UploadedFile[] | null;
  // Loading state
  isLoading: boolean;
  // Upload a new file and return the uploaded file with URL
  uploadFile: (file: File, fieldType: FieldType, fileType: FileType) => Promise<UploadedFile | null>;
  // Get file content as text (fetches from URL)
  getFileContent: (file: UploadedFile) => Promise<string | null>;
  // Delete a file
  deleteFile: (fileId: Id<'files'>) => Promise<void>;
  // Check if Convex is available
  isAvailable: boolean;
}

/**
 * Hook for managing uploaded files in Convex storage
 * Files are persisted and can be reused across sessions
 */
export function useUploadedFiles(fieldType: FieldType): UseUploadedFilesResult {
  const isAvailable = useConvexAvailable();
  const [isLoading, setIsLoading] = useState(false);

  // Queries - listByFieldType now includes URLs
  const files = useQuery(
    api.files.listByFieldType,
    isAvailable ? { fieldType } : 'skip'
  ) as UploadedFile[] | undefined;

  // Mutations
  const generateUploadUrl = useMutation(api.files.generateUploadUrl);
  const createFile = useMutation(api.files.create);
  const removeFile = useMutation(api.files.remove);

  // Upload a file to Convex storage (follows Convex 3-step pattern)
  const uploadFile = useCallback(async (
    file: File,
    fieldType: FieldType,
    fileType: FileType
  ): Promise<UploadedFile | null> => {
    if (!isAvailable) {
      console.warn('Convex not available, file will not be persisted');
      return null;
    }

    setIsLoading(true);
    try {
      // Step 1: Get a short-lived upload URL
      const postUrl = await generateUploadUrl();

      // Step 2: POST the file to the URL
      const result = await fetch(postUrl, {
        method: 'POST',
        headers: { 'Content-Type': file.type || 'application/octet-stream' },
        body: file,
      });

      if (!result.ok) {
        throw new Error(`Upload failed: ${result.statusText}`);
      }

      const { storageId } = await result.json();

      // Step 3: Save the storage ID to the database
      const fileId = await createFile({
        name: file.name,
        type: fileType,
        fieldType,
        storageId,
        size: file.size,
        runId: null,
      });

      // Return the created file info (URL will be available after query refreshes)
      return {
        _id: fileId,
        name: file.name,
        type: fileType,
        fieldType,
        storageId,
        size: file.size,
        createdAt: Date.now(),
        url: null, // URL will be available when query refreshes
      };
    } catch (error) {
      console.error('Failed to upload file:', error);
      throw error;
    } finally {
      setIsLoading(false);
    }
  }, [isAvailable, generateUploadUrl, createFile]);

  // Get file content as text by fetching from the URL
  const getFileContent = useCallback(async (file: UploadedFile): Promise<string | null> => {
    if (!file.url) {
      console.warn('File URL not available');
      return null;
    }

    try {
      const response = await fetch(file.url);
      if (response.ok) {
        return await response.text();
      }
      throw new Error(`Failed to fetch file: ${response.statusText}`);
    } catch (error) {
      console.error('Failed to fetch file content:', error);
      return null;
    }
  }, []);

  // Delete a file
  const deleteFile = useCallback(async (fileId: Id<'files'>): Promise<void> => {
    if (!isAvailable) return;
    await removeFile({ id: fileId });
  }, [isAvailable, removeFile]);

  return {
    files: isAvailable ? (files ?? null) : null,
    isLoading,
    uploadFile,
    getFileContent,
    deleteFile,
    isAvailable,
  };
}

/**
 * Hook to get all uploaded files (for browsing)
 * Returns files with URLs included
 */
export function useAllUploadedFiles() {
  const isAvailable = useConvexAvailable();
  
  const files = useQuery(
    api.files.listAll,
    isAvailable ? {} : 'skip'
  ) as UploadedFile[] | undefined;

  return {
    files: isAvailable ? (files ?? null) : null,
    isAvailable,
  };
}

/**
 * Format file size for display
 */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Format timestamp for display
 */
export function formatFileDate(timestamp: number): string {
  return new Date(timestamp).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}
