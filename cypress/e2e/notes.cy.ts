// eslint-disable-next-line @typescript-eslint/triple-slash-reference
/// <reference path="../support/index.d.ts" />

describe('Notes save flow', () => {
        const noteResponse = {
                id: 'note-123',
                user_id: 'user-1',
                title: '2024-05-01',
                data: {
                        content: {
                                html: 'Saved content',
                                md: 'Saved content',
                                json: null
                        }
                },
                meta: null,
                access_control: {},
                created_at: Date.now() * 1_000_000,
                updated_at: Date.now() * 1_000_000
        };

        beforeEach(() => {
                cy.loginAdmin();
        });

        it('creates a new note when arriving with saved content', () => {
                cy.intercept('GET', '/api/v1/notes/', {
                        statusCode: 200,
                        body: []
                }).as('listNotes');

                cy.intercept('POST', '/api/v1/notes/create', (req) => {
                        expect(req.body.title).to.match(/\d{4}-\d{2}-\d{2}/);
                        expect(req.body.data.content.html).to.eq('Saved content');
                        expect(req.body.data.content.md).to.eq('Saved content');
                        req.reply({ statusCode: 200, body: noteResponse });
                }).as('createNote');

                cy.intercept('GET', `/api/v1/notes/${noteResponse.id}`, {
                        statusCode: 200,
                        body: noteResponse
                }).as('loadNote');

                cy.visit('/notes?content=Saved%20content');

                cy.wait('@createNote');
                cy.url().should('include', `/notes/${noteResponse.id}`);
                cy.wait('@loadNote');
                cy.get('#note-container').should('be.visible');
        });

        it('shows an error toast when note creation fails', () => {
                cy.intercept('GET', '/api/v1/notes/', {
                        statusCode: 200,
                        body: []
                }).as('listNotes');

                cy.intercept('POST', '/api/v1/notes/create', {
                        statusCode: 500,
                        body: { detail: 'Server error' }
                }).as('createNote');

                cy.visit('/notes?content=Broken%20content');

                cy.wait('@createNote');
                cy.contains('Server error').should('be.visible');
                cy.url().should('include', '/notes?content=Broken%20content');
        });
});

