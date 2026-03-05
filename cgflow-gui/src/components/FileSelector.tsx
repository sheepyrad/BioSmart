import { useState, useCallback, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  useUploadedFiles,
  formatFileSize,
  formatFileDate,
  type FieldType,
  type FileType,
  type UploadedFile,
} from '@/hooks/useUploadedFiles';
import {
  FileUp,
  Check,
  ChevronDown,
  Cloud,
  HardDrive,
  Loader2,
  Trash2,
  Clock,
} from 'lucide-react';

interface FileSelectorProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  onContentLoaded?: (content: string) => void;
  fieldType: FieldType;
  fileType: FileType;
  accept: string;
  placeholder?: string;
  optional?: boolean;
  // For local file selection (IPC or web)
  onSelectLocal: () => Promise<string | null>;
  onReadLocalContent?: (path: string) => Promise<string>;
}

export default function FileSelector({
  label,
  value,
  onChange,
  onContentLoaded,
  fieldType,
  fileType,
  accept,
  placeholder = 'Select a file...',
  optional = false,
  onSelectLocal,
  onReadLocalContent,
}: FileSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dropdownPosition, setDropdownPosition] = useState({ top: 0, left: 0, width: 0 });

  // Update dropdown position when opening
  useEffect(() => {
    if (isOpen && containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect();
      setDropdownPosition({
        top: rect.bottom + 8, // 8px gap (mt-2)
        left: rect.left,
        width: rect.width,
      });
    }
  }, [isOpen]);

  // Close dropdown when clicking outside
  useEffect(() => {
    if (!isOpen) return;
    
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        // Check if click is inside the portal dropdown
        const dropdown = document.getElementById('file-selector-dropdown');
        if (dropdown && dropdown.contains(e.target as Node)) return;
        setIsOpen(false);
      }
    };
    
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);
  
  // Get previously uploaded files for this field type
  const { files, uploadFile, getFileContent, deleteFile, isAvailable } = useUploadedFiles(fieldType);

  // Handle selecting a previously uploaded file
  const handleSelectUploadedFile = useCallback(async (file: UploadedFile) => {
    setIsOpen(false);
    
    // Use the file URL as the path (will be recognized as a Convex file)
    if (file.url) {
      onChange(`convex://${file._id}::${file.name}`);
      
      // Load content if callback provided
      if (onContentLoaded) {
        const content = await getFileContent(file);
        if (content) {
          onContentLoaded(content);
        }
      }
    }
  }, [onChange, onContentLoaded, getFileContent]);

  // Handle selecting a local file
  const handleSelectLocal = useCallback(async () => {
    setIsOpen(false);
    const path = await onSelectLocal();
    if (path) {
      onChange(path);
      
      // Load content if callback provided
      if (onContentLoaded && onReadLocalContent) {
        const content = await onReadLocalContent(path);
        if (content) {
          onContentLoaded(content);
        }
      }
    }
  }, [onSelectLocal, onChange, onContentLoaded, onReadLocalContent]);

  // Handle uploading a new file to Convex
  const handleUploadNew = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    try {
      const uploaded = await uploadFile(file, fieldType, fileType);
      if (uploaded) {
        // The file list will auto-update, select it
        onChange(`convex://${uploaded._id}::${file.name}`);
        
        // Load content if callback provided
        if (onContentLoaded) {
          const content = await file.text();
          onContentLoaded(content);
        }
      }
    } catch (error) {
      console.error('Failed to upload file:', error);
    } finally {
      setIsUploading(false);
      setIsOpen(false);
      // Reset input
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  }, [uploadFile, fieldType, fileType, onChange, onContentLoaded]);

  // Handle deleting an uploaded file
  const handleDelete = useCallback(async (e: React.MouseEvent, fileId: UploadedFile['_id']) => {
    e.stopPropagation();
    await deleteFile(fileId);
  }, [deleteFile]);

  // Get display value
  const displayValue = value
    ? value.startsWith('convex://')
      ? value.split('::')[1] || 'Uploaded file'
      : value.split('/').pop() || value
    : '';

  const isConvexFile = value.startsWith('convex://');

  return (
    <div className="space-y-2">
      <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
        {label}
        {optional && <span className="text-muted-foreground/60 ml-1">(optional)</span>}
      </Label>
      
      <div ref={containerRef} className="relative">
        {/* Main input row */}
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Input
              value={displayValue}
              onChange={(e) => onChange(e.target.value)}
              placeholder={placeholder}
              className="bg-white pr-8"
            />
            {isConvexFile && (
              <Cloud className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-blue-500" />
            )}
            {!isConvexFile && value && (
              <HardDrive className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            )}
          </div>
          
          {/* Dropdown button */}
          <Button
            variant="outline"
            size="icon"
            onClick={() => setIsOpen(!isOpen)}
            className="shrink-0 hover-lift"
          >
            {isUploading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ChevronDown className={`h-4 w-4 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
            )}
          </Button>
          
          {/* Local file select button */}
          <Button
            variant="outline"
            size="icon"
            onClick={handleSelectLocal}
            className="shrink-0 hover-lift"
            title="Select from local filesystem"
          >
            <FileUp className="h-4 w-4" />
          </Button>
        </div>

        {/* Dropdown panel - rendered in portal to escape overflow clipping */}
        {isOpen && createPortal(
          <AnimatePresence>
            <motion.div
              id="file-selector-dropdown"
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="fixed bg-white rounded-lg border border-border shadow-lg overflow-hidden"
              style={{
                top: dropdownPosition.top,
                left: dropdownPosition.left,
                width: dropdownPosition.width,
                zIndex: 9999,
              }}
            >
              <div className="p-2 border-b border-border/50">
                <p className="text-xs font-medium text-muted-foreground">
                  {isAvailable ? 'Previously Uploaded Files' : 'Convex not connected'}
                </p>
              </div>

              {isAvailable && (
                <>
                  <ScrollArea className="max-h-48">
                    {files && files.length > 0 ? (
                      <div className="p-1">
                        {files.map((file) => (
                          <motion.button
                            key={file._id}
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            onClick={() => handleSelectUploadedFile(file)}
                            className="w-full text-left p-2 rounded-md hover:bg-slate-50 transition-colors flex items-center justify-between group"
                          >
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <Cloud className="h-3.5 w-3.5 text-blue-500 shrink-0" />
                                <span className="text-sm font-medium truncate">{file.name}</span>
                                {value.includes(file._id) && (
                                  <Check className="h-3.5 w-3.5 text-green-500 shrink-0" />
                                )}
                              </div>
                              <div className="flex items-center gap-2 mt-0.5 text-xs text-muted-foreground">
                                <span>{formatFileSize(file.size)}</span>
                                <span>•</span>
                                <Clock className="h-3 w-3" />
                                <span>{formatFileDate(file.createdAt)}</span>
                              </div>
                            </div>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-6 w-6 opacity-70 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive"
                              onClick={(e) => handleDelete(e, file._id)}
                              title="Delete uploaded file"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </motion.button>
                        ))}
                      </div>
                    ) : (
                      <div className="p-4 text-center text-sm text-muted-foreground">
                        No files uploaded yet
                      </div>
                    )}
                  </ScrollArea>

                  <div className="p-2 border-t border-border/50">
                    <label className="block">
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept={accept}
                        onChange={handleUploadNew}
                        className="hidden"
                      />
                      <Button
                        variant="outline"
                        size="sm"
                        className="w-full"
                        onClick={() => fileInputRef.current?.click()}
                        disabled={isUploading}
                      >
                        {isUploading ? (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                          <Cloud className="mr-2 h-4 w-4" />
                        )}
                        Upload & Save to Cloud
                      </Button>
                    </label>
                  </div>
                </>
              )}

              {!isAvailable && (
                <div className="p-4 text-center text-sm text-muted-foreground">
                  <p>Connect to Convex to save files</p>
                  <p className="text-xs mt-1">Files selected locally won't be persisted</p>
                </div>
              )}
            </motion.div>
          </AnimatePresence>,
          document.body
        )}
      </div>

      {/* Selected file indicator */}
      {value && (
        <div className="flex items-center gap-2">
          <Badge 
            variant="secondary" 
            className={`text-xs ${isConvexFile ? 'bg-blue-500/10 text-blue-600' : 'bg-slate-100 text-slate-600'}`}
          >
            {isConvexFile ? (
              <>
                <Cloud className="h-3 w-3 mr-1" />
                Cloud stored
              </>
            ) : (
              <>
                <HardDrive className="h-3 w-3 mr-1" />
                Local file
              </>
            )}
          </Badge>
        </div>
      )}
    </div>
  );
}
