<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe, fmtTime } from '../events.js';

  // B4.7: OSS branch lifecycle — fork-branch worktree creation through commit-identity assignment.
  let feed = $state([]); // {event_type, label, detail}
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    let label = '', detail = '';
    if (msg.event_type === 'oss_worktree_created') {
      label = 'worktree';
      detail = `${p.fork_branch} (${p.upstream_repo})`;
    } else if (msg.event_type === 'oss_pr_opened') {
      label = 'PR';
      detail = `#${p.pr_number} ${p.pr_repo} (${p.fork_branch})`;
    } else {
      label = 'commit';
      detail = `${p.identity_name} · ${(p.commit_sha || '').slice(0, 10)}`;
    }
    feed = [...feed, { event_type: msg.event_type, label, detail, received_at: msg.received_at }].slice(-50);
  }

  onMount(() => {
    unsubscribe = subscribe(['oss_worktree_created', 'commit_identity_assigned', 'oss_pr_opened'], apply, () => (connected = true));
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>OSS Branch</h2>
  <small>oss_worktree_created · commit_identity_assigned · oss_pr_opened</small>
  {#if feed.length === 0}
    <p>no OSS branch yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each feed as e, i (i)}
        <li><span class="ts">{fmtTime(e.received_at)}</span> <span>[{e.label}]</span> {e.detail}</li>
      {/each}
    </ul>
  {/if}
</section>
