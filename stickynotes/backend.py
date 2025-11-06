# Copyright © 2012-2015 Umang Varma <umang.me@gmail.com>
# 
# This file is part of indicator-stickynotes.
# 
# indicator-stickynotes is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
# 
# indicator-stickynotes is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
# 
# You should have received a copy of the GNU General Public License along with
# indicator-stickynotes.  If not, see <http://www.gnu.org/licenses/>.

from datetime import datetime, timedelta
import uuid
import json
from os.path import expanduser

from stickynotes.info import FALLBACK_PROPERTIES, DEFAULT_TRASH_RETENTION_DAYS, DEFAULT_CONFIRM_DELETE

class Note:
    def __init__(self, content=None, gui_class=None, noteset=None,
            category=None):
        self.gui_class = gui_class
        self.noteset = noteset
        content = content or {}
        self.uuid = content.get('uuid')
        self.body = content.get('body','')
        self.properties = content.get("properties", {})
        self.category = category or content.get("cat", "")
        if not self.category in self.noteset.categories:
            self.category = ""
        last_modified = content.get('last_modified')
        if last_modified:
            self.last_modified = datetime.strptime(last_modified,
                    "%Y-%m-%dT%H:%M:%S")
        else:
            self.last_modified = datetime.now()
        # Don't create GUI until show is called
        self.gui = None

    def extract(self):
        if not self.uuid:
            self.uuid = str(uuid.uuid4())
        if self.gui != None:
            self.gui.update_note()
            self.properties = self.gui.properties()
        return {"uuid":self.uuid, "body":self.body,
                "last_modified":self.last_modified.strftime(
                    "%Y-%m-%dT%H:%M:%S"), "properties":self.properties,
                "cat": self.category}

    def update(self,body=None):
        if not body == None:
            self.body = body
            self.last_modified = datetime.now()

    def delete(self):
        """Move note to archive instead of permanent deletion"""
        self.noteset.archive_note(self)
        self.noteset.save()

    def show(self, *args, **kwargs):
        # If GUI has not been created, create it now
        if self.gui == None:
            self.gui = self.gui_class(note=self)
        else:
            self.gui.show(*args, **kwargs)

    def hide(self):
        if self.gui != None:
            self.gui.hide()

    def set_locked_state(self, locked):
        # if gui hasn't been initialized, just change the property
        if self.gui == None:
            self.properties["locked"] = locked
        else:
            self.gui.set_locked_state(locked)

    def cat_prop(self, prop):
        """Gets a property of the note's category"""
        return self.noteset.get_category_property(self.category, prop)


class NoteSet:
    def __init__(self, gui_class, data_file, indicator):
        self.notes = []
        self.archived_notes = []  # Archive for deleted notes
        self.properties = {}
        self.categories = {}
        self.gui_class = gui_class
        self.data_file = data_file
        self.indicator = indicator

    def _loads_updater(self, dnoteset):
        """Parses old versions of the Notes structure and updates them"""
        return dnoteset

    def loads(self, snoteset):
        """Loads notes into their respective objects"""
        notes = self._loads_updater(json.loads(snoteset))
        self.properties = notes.get("properties", {})
        # Set default values for new properties
        if "trash_retention_days" not in self.properties:
            self.properties["trash_retention_days"] = DEFAULT_TRASH_RETENTION_DAYS
        if "confirm_delete" not in self.properties:
            self.properties["confirm_delete"] = DEFAULT_CONFIRM_DELETE
        self.categories = notes.get("categories", {})
        self.notes = [Note(note, gui_class=self.gui_class, noteset=self)
                for note in notes.get("notes",[])]
        # Load archived notes
        self.archived_notes = notes.get("archived_notes", [])
        # Clean up old archived notes
        self.cleanup_old_archived_notes()

    def dumps(self):
        return json.dumps({
            "notes": [x.extract() for x in self.notes],
            "archived_notes": self.archived_notes,
            "properties": self.properties,
            "categories": self.categories
        })

    def save(self, path=''):
        output = self.dumps()
        with open(path or expanduser(self.data_file),
                mode='w', encoding='utf-8') as fsock:
            fsock.write(output)

    def open(self, path=''):
        with open(path or expanduser(self.data_file), 
                encoding='utf-8') as fsock:
            self.loads(fsock.read())

    def load_fresh(self):
        """Load empty data"""
        self.loads('{}')
        self.new()

    def merge(self, data):
        """Update notes based on new data"""
        jdata = self._loads_updater(json.loads(data))
        self.hideall()
        # update categories
        if "categories" in jdata:
            self.categories.update(jdata["categories"])
        # make a dictionary of notes so we can modify existing notes
        dnotes = {n.uuid : n for n in self.notes}
        for newnote in jdata.get("notes", []):
            if "uuid" in newnote and newnote["uuid"] in dnotes:
                # Update notes that are already in the noteset
                orignote = dnotes[newnote["uuid"]]
                if "body" in newnote:
                    orignote.body = newnote["body"]
                if "properties" in newnote:
                    orignote.properties = newnote["properties"]
                if "cat" in newnote:
                    orignote.category = newnote["cat"]
            else:
                # otherwise create a new note
                if "uuid" in newnote:
                    uuid = newnote["uuid"]
                else:
                    uuid = str(uuid.uuid4())
                dnotes[uuid] = Note(newnote, gui_class=self.gui_class,
                        noteset=self)
        # copy notes over from dictionary to list
        self.notes = list(dnotes.values())
        self.showall(reload_from_backend=True)

    def new(self):
        """Creates a new note and adds it to the note set"""
        note = Note(gui_class=self.gui_class, noteset=self,
                category=self.properties.get("default_cat", ""))
        self.notes.append(note)
        note.show()
        return note

    def showall(self, *args, **kwargs):
        for note in self.notes:
            note.show(*args, **kwargs)
        self.properties["all_visible"] = True

    def hideall(self, *args):
        self.save()
        for note in self.notes:
            note.hide(*args)
        self.properties["all_visible"] = False
    def archive_note(self, note):
        """Move note to archive instead of permanent deletion"""
        # Remove from active notes
        if note in self.notes:
            self.notes.remove(note)
        
        # Extract note data and add deletion timestamp
        archived_data = note.extract()
        archived_data["deleted_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        
        # Add to archived notes
        self.archived_notes.append(archived_data)
        
        # Hide GUI if exists
        if note.gui:
            note.gui.winMain.destroy()

    def cleanup_old_archived_notes(self):
        """Remove archived notes older than retention period"""
        retention_days = self.properties.get("trash_retention_days", DEFAULT_TRASH_RETENTION_DAYS)
        if retention_days <= 0:
            return  # Keep notes forever if retention is 0 or negative
        
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        
        # Filter out old archived notes
        self.archived_notes = [
            note for note in self.archived_notes
            if datetime.strptime(note.get("deleted_at", "2000-01-01T00:00:00"), 
                                "%Y-%m-%dT%H:%M:%S") > cutoff_date
        ]

    def restore_note(self, archived_note_uuid):
        """Restore a note from archive"""
        # Find the archived note
        archived_note = None
        for note in self.archived_notes:
            if note.get("uuid") == archived_note_uuid:
                archived_note = note
                break
        
        if not archived_note:
            return None
        
        # Remove from archive
        self.archived_notes.remove(archived_note)
        
        # Remove deleted_at timestamp
        if "deleted_at" in archived_note:
            del archived_note["deleted_at"]
        
        # Create new note from archived data
        restored_note = Note(archived_note, gui_class=self.gui_class, noteset=self)
        self.notes.append(restored_note)
        
        # Save changes
        self.save()
        
        return restored_note

    def get_archived_notes(self):
        """Get list of archived notes with their metadata"""
        return self.archived_notes


    def get_category_property(self, cat, prop):
        """Get a property of a category or the default"""
        if ((not cat) or (not cat in self.categories)) and \
                self.properties.get("default_cat", None):
            cat = self.properties["default_cat"]
        cat_data = self.categories.get(cat, {})
        if prop in cat_data:
            return cat_data[prop]
        # Otherwise, use fallback categories
        if prop in FALLBACK_PROPERTIES:
            return FALLBACK_PROPERTIES[prop]
        else:
            raise ValueError("Unknown property")

class dGUI:
    """Dummy GUI"""
    def __init__(self, *args, **kwargs):
        pass
    def show(self):
        pass
    def hide(self):
        pass
    def update_note(self):
        pass
    def properties(self):
        return None

