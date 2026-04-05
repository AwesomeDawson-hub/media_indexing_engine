import { useState } from 'react';
import type { MetadataFields } from '../types/api';

interface MetadataDisplayProps {
  metadata: MetadataFields;
  onSave?: (updated: Partial<MetadataFields>) => Promise<void>;
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

type EditState = {
  title: string;
  description: string;
  tags: string;
  objects: string;
  scenes: string;
  context: string;
  mood: string;
  people: string;
  people_count: string;
  orientation: string;
  colors: string;
  location_hint: string;
  quality_notes: string;
};

function toEditState(m: MetadataFields): EditState {
  return {
    title: m.title,
    description: m.description,
    tags: m.tags.join(', '),
    objects: m.objects.join(', '),
    scenes: m.scenes.join(', '),
    context: m.context,
    mood: m.mood,
    people: m.people.join(', '),
    people_count: String(m.people_count),
    orientation: m.orientation,
    colors: m.colors.join(', '),
    location_hint: m.location_hint ?? '',
    quality_notes: m.quality_notes ?? '',
  };
}

function splitList(val: string): string[] {
  return val.split(',').map((s) => s.trim()).filter(Boolean);
}

export default function MetadataDisplay({ metadata, onSave }: MetadataDisplayProps) {
  const [editing, setEditing] = useState(false);
  const [editState, setEditState] = useState<EditState>(toEditState(metadata));
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');

  function startEdit() {
    setEditState(toEditState(metadata));
    setSaveError('');
    setEditing(true);
  }

  async function handleSave() {
    if (!onSave) return;
    setSaving(true);
    setSaveError('');
    try {
      await onSave({
        title: editState.title.trim(),
        description: editState.description.trim(),
        tags: splitList(editState.tags),
        objects: splitList(editState.objects),
        scenes: splitList(editState.scenes),
        context: editState.context.trim(),
        mood: editState.mood.trim(),
        people: splitList(editState.people),
        people_count: parseInt(editState.people_count, 10) || 0,
        orientation: editState.orientation.trim(),
        colors: splitList(editState.colors),
        location_hint: editState.location_hint.trim() || undefined,
        quality_notes: editState.quality_notes.trim() || undefined,
      });
      setEditing(false);
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  }

  function set(field: keyof EditState, value: string) {
    setEditState((prev) => ({ ...prev, [field]: value }));
  }

  if (editing) {
    return (
      <div className="metadata-display">
        <div className="metadata-edit-header">
          <span className="metadata-edit-title">Edit Metadata</span>
          <div className="metadata-edit-actions">
            <button className="btn btn-sm btn-primary" onClick={handleSave} disabled={saving}>
              {saving ? 'Saving...' : 'Save'}
            </button>
            <button className="btn btn-sm btn-outline" onClick={() => setEditing(false)} disabled={saving}>
              Cancel
            </button>
          </div>
        </div>
        {saveError && <div className="alert alert-danger" style={{ marginBottom: '12px' }}>{saveError}</div>}

        <div className="metadata-section">
          <h3>Metadata</h3>

          <div className="metadata-field">
            <label>Title</label>
            <input className="metadata-edit-input" value={editState.title} onChange={(e) => set('title', e.target.value)} maxLength={200} />
          </div>

          <div className="metadata-field">
            <label>Description</label>
            <textarea className="metadata-edit-textarea" value={editState.description} onChange={(e) => set('description', e.target.value)} rows={3} />
          </div>

          <div className="metadata-field">
            <label>Tags <span className="metadata-edit-hint">(comma-separated)</span></label>
            <input className="metadata-edit-input" value={editState.tags} onChange={(e) => set('tags', e.target.value)} />
          </div>

          <div className="metadata-field">
            <label>Mood</label>
            <input className="metadata-edit-input" value={editState.mood} onChange={(e) => set('mood', e.target.value)} maxLength={100} />
          </div>

          <div className="metadata-field">
            <label>People <span className="metadata-edit-hint">(comma-separated)</span></label>
            <input className="metadata-edit-input" value={editState.people} onChange={(e) => set('people', e.target.value)} />
          </div>

          <div className="metadata-field">
            <label>People Count</label>
            <input className="metadata-edit-input" type="number" min={0} value={editState.people_count} onChange={(e) => set('people_count', e.target.value)} style={{ width: '80px' }} />
          </div>

          <div className="metadata-field">
            <label>Orientation</label>
            <select className="metadata-edit-input" value={editState.orientation} onChange={(e) => set('orientation', e.target.value)}>
              <option value="landscape">landscape</option>
              <option value="portrait">portrait</option>
              <option value="square">square</option>
            </select>
          </div>
        </div>

        <div className="metadata-section">
          <h3>Additional Search Data</h3>

          <div className="metadata-field">
            <label>Objects <span className="metadata-edit-hint">(comma-separated)</span></label>
            <input className="metadata-edit-input" value={editState.objects} onChange={(e) => set('objects', e.target.value)} />
          </div>

          <div className="metadata-field">
            <label>Scenes <span className="metadata-edit-hint">(comma-separated)</span></label>
            <input className="metadata-edit-input" value={editState.scenes} onChange={(e) => set('scenes', e.target.value)} />
          </div>

          <div className="metadata-field">
            <label>Context</label>
            <textarea className="metadata-edit-textarea" value={editState.context} onChange={(e) => set('context', e.target.value)} rows={2} />
          </div>

          <div className="metadata-field">
            <label>Colors <span className="metadata-edit-hint">(comma-separated)</span></label>
            <input className="metadata-edit-input" value={editState.colors} onChange={(e) => set('colors', e.target.value)} />
          </div>

          <div className="metadata-field">
            <label>Location Hint</label>
            <input className="metadata-edit-input" value={editState.location_hint} onChange={(e) => set('location_hint', e.target.value)} maxLength={200} />
          </div>

          <div className="metadata-field">
            <label>Quality Notes</label>
            <textarea className="metadata-edit-textarea" value={editState.quality_notes} onChange={(e) => set('quality_notes', e.target.value)} rows={2} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="metadata-display">
      {onSave && (
        <div className="metadata-view-header">
          <button className="btn btn-sm btn-outline" onClick={startEdit}>Edit</button>
        </div>
      )}
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

