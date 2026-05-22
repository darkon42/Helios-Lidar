<!--
Thanks for contributing to Helios-Lidar!

Pick the section that matches what your PR is about and fill it in.
Delete the sections that don't apply.

For most non-trivial changes (anything beyond a typo fix), please open
an issue first so we can align on the approach before you spend time
on a PR.
-->

## Adding a new LiDAR source to `LIDAR_SOURCES.md`

Use this section if your PR only adds (or fixes) a country / region
entry in `LIDAR_SOURCES.md`. Fill in everything below.

### Country / region

What you're adding. Include the level of granularity: nation-wide,
single state, single canton, etc.

### Proposed entry

The bullet you're adding, in the exact `LIDAR_SOURCES.md` format:

```markdown
* **Country (region if not nation-wide)**, [Portal name](url).
  Optional one-line note (license, granularity, format quirk).
```

### Proof the source actually feeds Helios-Lidar

Run a conversion on [helios-lidar.org](https://helios-lidar.org) with
data downloaded from your proposed portal. Attach a screenshot of the
result panel showing:

* the 3D preview rendered,
* the `Download` button with the generated `.tif` filename,
* the YAML snippet block populated.

A screenshot is enough, the actual `.tif` and YAML do not need to be
shared. Reviewers use this to confirm that the portal you're adding
produces data the pipeline can actually consume end-to-end.

<!-- paste the screenshot here -->

### Notes for reviewers

Anything specific reviewers should know (paywalled tier, registration
required, regional restrictions, etc.). Leave blank if nothing
special applies.

---

## Other changes (code, UI, deploy, docs)

Use this section if your PR is not about `LIDAR_SOURCES.md`. Replace
the placeholders below with what fits, and delete what doesn't apply.

### Summary

One-paragraph description of what changes and why.

### Test plan

How you verified the change works. Steps a reviewer can follow to
reproduce, or output from automated checks.

### Related issue

`Fixes #<number>` if there's an issue. Otherwise leave blank.
