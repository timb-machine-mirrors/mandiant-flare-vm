#!/usr/bin/python3
# Copyright 2024 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import argparse
import re
import sys
import textwrap

from vboxcommon import *


def get_snapshot_children(vm_name, root_snapshot_name, protected_snapshots):
    """Get the children of a snapshot (including the snapshot) using 'VBoxManage snapshot' with the 'list' option.

    Args:
      vm_name: The name of the VM.
      root_snapshot_name: The name of the root snapshot we want the children of.
      protected_snapshots: snapshots we ignore and do not include in the returned list

    Returns:
      A list of snapshot names that are children of the given snapshot. The list is ordered by dependent relationships.
    """
    try:
        # Example of `VBoxManage snapshot VM_NAME list --machinereadable` output:
        # SnapshotName="ROOT"
        # SnapshotUUID="86b38fc9-9d68-4e4b-a033-4075002ab570"
        # SnapshotName-1="Snapshot 1"
        # SnapshotUUID-1="e383e702-fee3-4e0b-b1e0-f3b869dbcaea"
        # CurrentSnapshotName="Snapshot 1"
        # CurrentSnapshotUUID="e383e702-fee3-4e0b-b1e0-f3b869dbcaea"
        # CurrentSnapshotNode="SnapshotName-1"
        # SnapshotName-1-1="Snapshot 2"
        # SnapshotUUID-1-1="8cc12787-99df-466e-8a51-80e373d3447a"
        # SnapshotName-2="Snapshot 3"
        # SnapshotUUID-2="f42533a8-7c14-4855-aa66-7169fe8187fe"
        #
        # ROOT
        #   ├─ Snapshot 1
        #   │   └─ Snapshot 2
        #   └─ Snapshot 3

        snapshots_info = run_vboxmanage(["snapshot", vm_name, "list", "--machinereadable"])
        # Find all snapshot names
        snapshot_regex = rf"(^SnapshotName(?:-\d+)*)=\"(.*?)\""
        snapshots = re.findall(snapshot_regex, snapshots_info, flags=re.M)

        children = []

        # find the root SnapshotName by matching the name
        root_snapshotid = None
        for snapshotid, snapshot_name in snapshots:
            if snapshot_name.lower() == root_snapshot_name.lower():
                root_snapshotid = snapshotid

        if not root_snapshotid:
            raise Exception(f"Failed to find root snapshot {snapshot_name}")

        # children of that snapshot share the same prefix id
        dependant_child = False
        for snapshotid, snapshot_name in snapshots:
            if snapshotid.startswith(root_snapshotid):
                if not any(
                    p.lower() in snapshot_name.lower() for p in protected_snapshots
                ):
                    children.append((snapshotid, snapshot_name))
                else:
                    dependant_child = True

        # remove the root snapshot if any children are protected OR it's the current snapshot
        if dependant_child:
            print("Root snapshot cannot be deleted as a child snapshot is protected")
            children = [
                snapshot for snapshot in children if snapshot[0] != root_snapshotid
            ]
        return children
    except Exception as e:
        raise Exception(f"Could not get snapshot children for '{vm_name}'") from e


def delete_snapshot_and_children(vm_name, snapshot_name, protected_snapshots):
    snaps_to_delete = get_snapshot_children(vm_name, snapshot_name, protected_snapshots)

    if snaps_to_delete:
        print(f"\nCleaning {vm_name} 🫧 Snapshots to delete:")
        for snapshotid, snapshot_name in snaps_to_delete:
            print(f"  {snapshot_name}")

        vm_state = get_vm_state(vm_name)
        if vm_state not in ("poweroff", "saved"):
            print(
                f"\nVM state: {vm_state}\n⚠️  Snapshot deleting is slower in a running VM and may fail in a changing state"
            )

        answer = input("\nConfirm deletion (press 'y'):")
        if answer.lower() == "y":
            print("\nDeleting... (this may take some time, go for an 🍦!)")
            for snapshotid, snapshot_name in reversed(
                snaps_to_delete
            ):  # delete in reverse order to avoid issues with child snapshots
                try:
                    run_vboxmanage(["snapshot", vm_name, "delete", snapshot_name])
                    print(f"  🫧 DELETED '{snapshot_name}'")
                except Exception as e:
                    print(f"  ❌ ERROR '{snapshot_name}'\n{e}")
    else:
        print(f"\n{vm_name} is clean 🫧")

    print("\nSee you next time you need to clean up your VMs! ✨\n")


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    epilog = textwrap.dedent(
        """
        Example usage:
          # Delete all snapshots that do not include 'clean' or 'done' in the name (case insensitive) in the 'FLARE-VM.20240604' VM
          vbox-clean-snapshots.py FLARE-VM.20240604

          # Delete all snapshots that do not include 'clean', 'done', or 'important in the name in the 'FLARE-VM.20240604' VM
          vbox-clean-snapshots.py FLARE-VM.20240604 --protected_snapshots "clean,done,important"

          # Delete the 'CLEAN with IDA 8.4' children snapshots recursively skipping the ones that include 'clean' or 'done' in the name (case insensitive) in the 'FLARE-VM.20240604' VM
          # NOTE: the 'CLEAN with IDA 8.4' root snapshot is skipped in this case
          vbox-clean-snapshots.py FLARE-VM.20240604 --root_snapshot CLEAN with IDA 8.4

          # Delete the 'Snapshot 3' snapshot and its children recursively skipping the ones that include 'clean' or 'done' in the name (case insensitive) in the 'FLARE-VM.20240604' VM
          vbox-clean-snapshots.py FLARE-VM.20240604 --root_snapshot Snapshot 3

          # Delete all snapshots in the 'FLARE-VM.20240604' VM
          vbox-clean-snapshots.py FLARE-VM.20240604 --protected_snapshots ""
        """
    )
    parser = argparse.ArgumentParser(
        description="Clean a VirtualBox VM up by deleting a snapshot and its children recursively skipping snapshots with a substring in the name.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("vm_name", help="Name of the VM to clean up")
    parser.add_argument(
        "--root_snapshot",
        default="",
        help="Snapshot to delete (and its children recursively). Leave empty to clean all snapshots in the VM.",
    )
    parser.add_argument(
        "--protected_snapshots",
        default="clean,done",
        type=lambda s: s.split(","),
        help='Comma-separated list of strings. Snapshots with any of the strings included in the name (case insensitive) are not deleted. Default: "clean,done"',
    )
    args = parser.parse_args(args=argv)

    delete_snapshot_and_children(
        args.vm_name, args.root_snapshot, args.protected_snapshots
    )


if __name__ == "__main__":
    main()
