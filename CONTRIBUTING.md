# Contributing to ewp-waveform

Contributions to `ewp-waveform` are welcome.

## Before changing behavior

Read:

- [`docs/README.md`](./docs/README.md) for the documentation index and normative precedence;
- [`docs/02-requirements.md`](./docs/02-requirements.md), [`docs/03-architecture.md`](./docs/03-architecture.md), and relevant ADRs;
- schemas under [`schemas/`](./schemas/);
- [`AGENTS.md`](./AGENTS.md) for implementation boundaries;
- [`LICENSING.md`](./LICENSING.md) for the project's licensing model; and
- [`CONTRIBUTOR_TERMS.md`](./CONTRIBUTOR_TERMS.md) for the terms that apply to submitted Contributions.

Do not duplicate those documents here.

## Engineering workflow

Use small, coherent [Conventional Commits](https://www.conventionalcommits.org/). Reference requirement IDs and ADRs where applicable.

Update [`CHANGELOG.md`](./CHANGELOG.md) for user-visible CLI, workflow, schema, installation, or accepted architectural-contract changes.

## Data hygiene

Never commit:

- private podcast audio;
- generated waveform media;
- workdirs, caches, or temporary outputs;
- benchmark bundles containing private media; or
- third-party binaries intended to be installed externally.

Do not add sample audio until renderer testing is ready. When samples are added, they must be identified excerpts from material the Project Licensor has the right to include (including **Etyka w Pętli (Ethics in the Loop)** excerpts licensed under **CC BY-NC-SA 4.0** where applicable). Those samples are for examples and determinism fixtures, not complete episode dumps.

## License

`ewp-waveform` is publicly source-available under the **EWP Waveform Community License 1.0**.

It is not Open Source software in the OSI sense because the public license contains commercial-use and commercial-redistribution restrictions.

The complete terms are in [`LICENSE`](./LICENSE). [`LICENSING.md`](./LICENSING.md) is a plain-language overview and does not replace the License.

## Pull Requests

When submitting a pull request:

1. keep the change focused and explain its purpose;
2. add or update tests where appropriate;
3. update documentation when behavior or user-facing interfaces change;
4. identify any third-party code, data, text, audio, video, images, fonts,
   models, assets, or other material included in the Contribution;
5. ensure that you have the right to submit all material contained in the pull
   request; and
6. affirmatively accept the Contributor Terms using the checkbox in the
   pull-request template.

A pull request should not be merged unless the Contributor Terms checkbox has
been affirmatively selected by the contributor.

## Third-Party Material

Do not submit third-party code, data, media, text, audio, video, images, fonts,
models, model weights, or other material unless its provenance and applicable
license terms are clearly identified and are compatible with the Project.

If you are unsure whether third-party material may be included, describe its
source and license in the pull request rather than assuming compatibility.

## Samples and Example Materials

The Project may later include sample or example material derived from
**Etyka w Pętli (Ethics in the Loop)**.

Where such material is identified as being licensed under
**CC BY-NC-SA 4.0**, contributions that modify or add to those samples must
respect that separate license.

Do not submit excerpts from third-party podcasts, recordings, videos, images, or
other copyrighted works as examples unless their inclusion has been expressly
discussed and their licensing is clearly compatible with the Project.

## External Dependencies

Do not add third-party dependencies, bundled binaries, downloadable packages, or
external assets without clearly identifying their source and license.

Where possible, optional third-party dependencies should remain separate from
the repository and should be downloaded only after explicit user confirmation.

## Contributor Terms

By submitting a Contribution through a pull request that references the
Contributor Terms and affirmatively selecting the acceptance checkbox, you agree
to the version of [`CONTRIBUTOR_TERMS.md`](./CONTRIBUTOR_TERMS.md) in effect for
that submission.

Contributors retain copyright ownership of their Contributions while granting
the rights described in the Contributor Terms.

## Upstream Contributions

The EWP Waveform Community License permits certain noncommercial distribution of
Modified Versions and forks.

While upstream contribution is not mandatory, users are strongly encouraged to
submit generally useful bug fixes, improvements, compatibility changes, and
features back to the original Project as pull requests.

## Review and Acceptance

Submission does not guarantee acceptance.

The Project Licensor or maintainers may request changes, reject a pull request,
or decline material whose provenance, licensing, security, maintainability,
scope, compatibility, or technical quality is unclear or unsuitable for the
Project.

## Project Licensor

**Damian Szczech**  
Email: szczech.dam+ewpwaveform@gmail.com
