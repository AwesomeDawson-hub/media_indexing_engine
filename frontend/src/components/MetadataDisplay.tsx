import type { MetadataFields } from '../types/api';

interface MetadataDisplayProps {
  metadata: MetadataFields;
}

function PillList({ items, className }: { items: string[]; className?: string }) {
  if (!items || items.length === 0) return <span className="text-muted">None</span>;
  return (
    <div className="pill-list">
      {items.map((item, i) => (
        <span key={i} className={`pill ${className || ''}`}>
          {item}
        </span>
      ))}
    </div>
  );
}

export default function MetadataDisplay({ metadata }: MetadataDisplayProps) {
  return (
    <div className="metadata-display">
      <div className="metadata-section">
        <h3>Metadata</h3>

        <div className="metadata-field">
          <label>Title</label>
          <p>{metadata.title || 'Untitled'}</p>
        </div>

        <div className="metadata-field">
          <label>Description</label>
          <p>{metadata.description || 'No description'}</p>
        </div>

        <div className="metadata-field">
          <label>Tags</label>
          <PillList items={metadata.tags} />
        </div>

        <div className="metadata-field">
          <label>Mood</label>
          <p>{metadata.mood || 'N/A'}</p>
        </div>

        <div className="metadata-field">
          <label>People</label>
          <PillList items={metadata.people} className="pill-green" />
        </div>

        <div className="metadata-field">
          <label>People Count</label>
          <p>{metadata.people_count}</p>
        </div>

        <div className="metadata-field">
          <label>Orientation</label>
          <p>{metadata.orientation || 'N/A'}</p>
        </div>
      </div>

      <div className="metadata-section">
        <h3>Additional Search Data</h3>

        <div className="metadata-field">
          <label>Objects</label>
          <PillList items={metadata.objects} className="pill-blue" />
        </div>

        <div className="metadata-field">
          <label>Scenes</label>
          <PillList items={metadata.scenes} className="pill-purple" />
        </div>

        <div className="metadata-field">
          <label>Context</label>
          <p>{metadata.context || 'N/A'}</p>
        </div>

        <div className="metadata-field">
          <label>Colors</label>
          <PillList items={metadata.colors} className="pill-color" />
        </div>

        {metadata.location_hint && (
          <div className="metadata-field">
            <label>Location Hint</label>
            <p>{metadata.location_hint}</p>
          </div>
        )}

        {metadata.quality_notes && (
          <div className="metadata-field">
            <label>Quality Notes</label>
            <p>{metadata.quality_notes}</p>
          </div>
        )}

        {metadata.ocr_text && (
          <div className="metadata-field">
            <label>Extracted Text (OCR)</label>
            <p style={{ fontFamily: 'monospace', fontSize: '0.85em', maxHeight: '120px', overflowY: 'auto', wordBreak: 'break-word', margin: 0, padding: '4px 0' }}>{metadata.ocr_text}</p>
          </div>
        )}
      </div>
    </div>
  );
}
